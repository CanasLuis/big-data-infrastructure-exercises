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

from bdi_api.settings import Settings

settings = Settings()

# AWS S3 session
session = boto3.Session(
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
    region_name="us-east-1"
)

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
    """Download JSON files and store them directly in S3."""
    base_url = settings.source_url + "/2023/11/01/"
    s3_bucket = settings.s3_bucket
    s3_prefix_path = "raw/day=20231101/"  # Se mantiene la estructura

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

@s4.post("/aircraft/prepare")
def prepare_data() -> str:
    """Read aircraft data from S3, process it, and save cleaned JSON back to S3."""
    s3_bucket = settings.s3_bucket
    raw_prefix = "raw/day=20231101/"
    prepared_prefix = "prepared/day=20231101/"

    # List files from S3
    raw_files = s3_client.list_objects_v2(Bucket=s3_bucket, Prefix=raw_prefix).get("Contents", [])
    if not raw_files:
        logging.error("No raw data found in S3.")
        return "No valid data found."

    all_aircraft_data = []

    for file_obj in raw_files:
        file_key = file_obj["Key"]
        try:
            # Obtener el objeto desde S3
            file_response = s3_client.get_object(Bucket=s3_bucket, Key=file_key)
            file_content = file_response["Body"].read().decode("utf-8")  # Leer y decodificar directamente como JSON

            # Convertir a JSON sin intentar descomprimir
            file_data = json.loads(file_content)

            # Procesar los datos de aeronaves
            aircraft_data = [
                {
                    "icao": aircraft.get("hex"),
                    "registration": aircraft.get("r"),
                    "type": aircraft.get("t"),
                    "latitude": aircraft.get("lat"),
                    "longitude": aircraft.get("lon"),
                    "alt_baro": None if aircraft.get("alt_baro") == "ground" else aircraft.get("alt_baro"),
                    "gs": aircraft.get("gs", None),
                    "emergency": aircraft.get("emergency", False),
                    "timestamp": file_data.get("now"),
                }
                for aircraft in file_data.get("aircraft", [])
                if aircraft.get("hex") and aircraft.get("lat") and aircraft.get("lon")
            ]

            if not aircraft_data:
                logging.warning(f"No aircraft data found in {file_key}")
                continue

            all_aircraft_data.extend(aircraft_data)

        except Exception as e:
            logging.warning(f"Failed to process file {file_key}: {e}")

    if not all_aircraft_data:
        logging.error("No valid aircraft data found.")
        return "No valid data found."

    # Convertir datos a JSON y subir a S3
    cleaned_data = json.dumps({"aircraft": all_aircraft_data})

    try:
        s3_client.put_object(
            Bucket=s3_bucket,
            Key=os.path.join(prepared_prefix, "merged_aircraft_data.json"),
            Body=cleaned_data,
            ContentType="application/json",
        )
    except Exception as e:
        logging.error(f"Failed to upload processed data to S3: {e}")
        return f"Failed to upload processed data to S3: {e}"

    return f"Data preparation completed successfully! File saved in S3 at {prepared_prefix}merged_aircraft_data.json"
