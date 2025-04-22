from airflow import DAG
from airflow.decorators import task
from airflow.utils.dates import days_ago

import boto3
import json
import logging
import gzip
from io import BytesIO
from datetime import datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'retries': 0
}


dates = [datetime(2023, month, 1).strftime("%Y%m%d") for month in range(11, 13)] + \
        [datetime(2024, month, 1).strftime("%Y%m%d") for month in range(1, 12)]

dag = DAG(
    dag_id='prepare_readsb_data_dag',
    description='Prepare readsb JSON.gz files from S3 RAW and generate Parquet + index in S3 PREPARED',
    default_args=default_args,
    schedule_interval=None,
    start_date=datetime(2023, 11, 1),
    catchup=False,
    tags=['prepare', 'readsb']
)

@task()
def prepare_data():
    bucket = "bdi-aircraft-luis-canas"
    s3 = boto3.client("s3")

    for day in dates:
        raw_prefix = f"raw/day={day}/"
        prepared_prefix = f"prepared/day={day}/"

        logging.info(f"Processing day {day}")
        raw_files = s3.list_objects_v2(Bucket=bucket, Prefix=raw_prefix).get("Contents", [])

        if not raw_files:
            logging.warning(f"No files found in raw bucket for day {day}.")
            continue

        raw_files = raw_files[:100]

        record_buffer = []
        parquet_part = 0
        index_map = {}

        def parse_emergency(value):
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.lower() == "none":
                return False
            if pd.isna(value):
                return False
            return bool(value)

        def flush_to_s3(buffer, part_number):
            df = pd.DataFrame(buffer)
            logging.info(f"Flushing part {part_number} with {len(df)} records")
            table = pa.Table.from_pandas(df)
            buf = BytesIO()
            pq.write_table(table, buf, compression="snappy")
            buf.seek(0)
            s3_key = f"{prepared_prefix}data_part_{part_number}.parquet"
            s3.upload_fileobj(buf, bucket, s3_key)
            return df['icao'].dropna().unique().tolist()

        for file_obj in raw_files:
            file_key = file_obj["Key"]
            try:
                file_response = s3.get_object(Bucket=bucket, Key=file_key)
                
                file_content = gzip.decompress(file_response["Body"].read()).decode("utf-8")
                file_data = json.loads(file_content)

                aircraft_list = file_data.get("aircraft", [])
                if not aircraft_list:
                    logging.warning(f"No aircraft data in file {file_key}")
                    continue

                for aircraft in aircraft_list:
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
                        icaos_in_part = flush_to_s3(record_buffer, parquet_part)
                        index_map[f"data_part_{parquet_part}.parquet"] = icaos_in_part
                        parquet_part += 1
                        record_buffer.clear()

            except Exception as e:
                logging.warning(f"Failed to process file {file_key} for day {day}: {e}")

        if record_buffer:
            icaos_in_part = flush_to_s3(record_buffer, parquet_part)
            index_map[f"data_part_{parquet_part}.parquet"] = icaos_in_part

        logging.info(f"Index map for day {day}: {json.dumps(index_map, indent=2)}")

        index_buf = BytesIO(json.dumps(index_map).encode("utf-8"))
        s3.upload_fileobj(index_buf, bucket, f"{prepared_prefix}index.json")

with dag:
    prepare_data()
