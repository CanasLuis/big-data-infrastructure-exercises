import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from urllib.parse import urljoin

import boto3
import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query, status
from tqdm import tqdm
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from bdi_api.settings import Settings

settings = Settings()

# AWS S3 session
session = boto3.Session()
s3_client = session.client("s3")

s4 = APIRouter(
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Not found"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "Invalid request"},
    },
    prefix="/api/s4",
    tags=["s4"],
)

@s4.post("/aircraft/download")
def download_data(
    file_limit: int = Query(..., description="Number of files to download"),
) -> str:
    base_url = settings.source_url + "/2023/11/01/"
    s3_bucket = settings.s3_bucket
    s3_prefix_path = "raw/day=20231101/"

    try:
        response = requests.get(base_url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        files = [a["href"] for a in soup.find_all("a") if a["href"].endswith(".json.gz")][:file_limit]

        def fetch_and_upload(file_name):
            file_url = urljoin(base_url, file_name)
            response = requests.get(file_url, stream=True)
            if response.status_code == 200:
                s3_object_name = os.path.join(s3_prefix_path, file_name).replace("\\", "/")
                s3_client.upload_fileobj(BytesIO(response.content), s3_bucket, s3_object_name)

        with ThreadPoolExecutor(max_workers=5) as executor:
            list(tqdm(executor.map(fetch_and_upload, files), total=len(files), desc="Downloading and uploading files"))

    except requests.RequestException as e:
        logging.error(f"Error accessing URL: {str(e)}")
        return f"Error accessing URL: {str(e)}"

    return "OK"

# Function to normalize 'emergency' values
def parse_emergency(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() == "none":
        return False
    if pd.isna(value):
        return False
    return bool(value)

@s4.post("/aircraft/prepare")
def prepare_data() -> str:
    s3_bucket = settings.s3_bucket
    raw_prefix = "raw/day=20231101/"
    prepared_prefix = "prepared/day=20231101/"

    raw_files = s3_client.list_objects_v2(Bucket=s3_bucket, Prefix=raw_prefix).get("Contents", [])
    if not raw_files:
        logging.error("No raw data found in S3.")
        return "No valid data found."

    record_buffer = []
    parquet_part = 0
    index_map = {}

    def flush_to_s3(buffer, part_number):
        df = pd.DataFrame(buffer)
        table = pa.Table.from_pandas(df)
        buf = BytesIO()
        pq.write_table(table, buf, compression="snappy")
        buf.seek(0)
        s3_key = f"{prepared_prefix}data_part_{part_number}.parquet"
        s3_client.upload_fileobj(buf, s3_bucket, s3_key)
        return df['icao'].unique().tolist()

    for file_obj in raw_files:
        file_key = file_obj["Key"]
        try:
            file_response = s3_client.get_object(Bucket=s3_bucket, Key=file_key)
            file_content = file_response["Body"].read().decode("utf-8")
            file_data = json.loads(file_content)

            for aircraft in file_data.get("aircraft", []):
                if not (aircraft.get("hex") and aircraft.get("lat") and aircraft.get("lon")):
                    continue

                record = {
                    "icao": aircraft.get("hex"),
                    "registration": aircraft.get("r"),
                    "type": aircraft.get("t"),
                    "latitude": aircraft.get("lat"),
                    "longitude": aircraft.get("lon"),
                    "alt_baro": None if aircraft.get("alt_baro") == "ground" else aircraft.get("alt_baro"),
                    "gs": aircraft.get("gs"),
                    "emergency": parse_emergency(aircraft.get("emergency")),
                    "timestamp": file_data.get("now"),
                }
                record_buffer.append(record)

                if len(record_buffer) % 10000 == 0:
                    df_tmp = pd.DataFrame(record_buffer)
                    table_tmp = pa.Table.from_pandas(df_tmp)
                    buf_tmp = BytesIO()
                    pq.write_table(table_tmp, buf_tmp, compression="snappy")
                    size_mb = buf_tmp.tell() / 1024 / 1024
                    if size_mb >= 100:
                        icaos_in_part = flush_to_s3(record_buffer, parquet_part)
                        index_map[f"data_part_{parquet_part}.parquet"] = icaos_in_part
                        parquet_part += 1
                        record_buffer.clear()

        except Exception as e:
            logging.warning(f"Failed to process file {file_key}: {e}")

    if record_buffer:
        icaos_in_part = flush_to_s3(record_buffer, parquet_part)
        index_map[f"data_part_{parquet_part}.parquet"] = icaos_in_part

    index_buf = BytesIO(json.dumps(index_map).encode("utf-8"))
    s3_client.upload_fileobj(index_buf, s3_bucket, f"{prepared_prefix}index.json")

    return f"Parquet files saved in S3 at {prepared_prefix} with index.json."
