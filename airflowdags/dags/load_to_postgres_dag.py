from airflow import DAG
from airflow.decorators import task
from airflow.utils.dates import days_ago

import boto3
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import logging
import os
from io import BytesIO  


default_args = {
    'owner': 'airflow',
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}


dates = [datetime(2023, month, 1).strftime("%Y%m%d") for month in range(11, 13)] + \
        [datetime(2024, month, 1).strftime("%Y%m%d") for month in range(1, 12)]

dag = DAG(
    dag_id='load_to_postgres_dag',
    default_args=default_args,
    description='Load Parquet files from S3 PREPARED to Postgres LOCAL',
    schedule_interval=None,
    start_date=datetime(2023, 11, 1),
    catchup=False,
    tags=['load', 'postgres']
)

@task()
def load_to_postgres():
    bucket = "bdi-aircraft-luis-canas"
    s3 = boto3.client("s3")

    
    postgres_host = os.getenv("POSTGRES_HOST")
    postgres_port = os.getenv("POSTGRES_PORT")
    postgres_db = os.getenv("POSTGRES_DB")
    postgres_user = os.getenv("POSTGRES_USER")
    postgres_password = os.getenv("POSTGRES_PASSWORD")

    logging.info(f"POSTGRES_HOST: {postgres_host}")
    logging.info(f"POSTGRES_PORT: {postgres_port}")
    logging.info(f"POSTGRES_DB: {postgres_db}")
    logging.info(f"POSTGRES_USER: {postgres_user}")
    logging.info(f"POSTGRES_PASSWORD: {postgres_password}")

    if not all([postgres_host, postgres_port, postgres_db, postgres_user, postgres_password]):
        raise ValueError("One or more PostgreSQL environment variables are not defined")

    try:
        conn = psycopg2.connect(
            host=postgres_host,
            port=postgres_port,
            database=postgres_db,
            user=postgres_user,
            password=postgres_password
        )
        logging.info("Successfully connected to PostgreSQL")
    except Exception as e:
        logging.error(f"Failed to connect to PostgreSQL: {str(e)}")
        raise

    cursor = conn.cursor()

    
    create_table_query = """
    CREATE TABLE IF NOT EXISTS aircraft_positions (
        icao VARCHAR(10),
        registration VARCHAR(20),
        type VARCHAR(10),
        latitude FLOAT,
        longitude FLOAT,
        alt_baro FLOAT,
        gs FLOAT,
        emergency BOOLEAN,
        timestamp FLOAT
    );
    """
    cursor.execute(create_table_query)
    conn.commit()

    for day in dates:
        prepared_prefix = f"prepared/day={day}/"
        logging.info(f"Processing day {day}")

        parquet_files = s3.list_objects_v2(Bucket=bucket, Prefix=prepared_prefix).get("Contents", [])
        parquet_files = [f for f in parquet_files if f["Key"].endswith(".parquet")]

        if not parquet_files:
            logging.warning(f"No Parquet files found for day {day}")
            continue

        for file_obj in parquet_files:
            file_key = file_obj["Key"]
            logging.info(f"Reading Parquet file {file_key}")

            try:
                response = s3.get_object(Bucket=bucket, Key=file_key)
                parquet_data = response["Body"].read()
                df = pd.read_parquet(BytesIO(parquet_data))  

                records = [
                    (
                        row['icao'], row['registration'], row['type'],
                        row['latitude'], row['longitude'], row['alt_baro'],
                        row['gs'], row['emergency'], row['timestamp']
                    )
                    for _, row in df.iterrows()
                ]

                insert_query = """
                INSERT INTO aircraft_positions (
                    icao, registration, type, latitude, longitude,
                    alt_baro, gs, emergency, timestamp
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
                """
                cursor.executemany(insert_query, records)
                conn.commit()
                logging.info(f"Loaded {len(records)} rows from {file_key} to PostgreSQL")
            except Exception as e:
                logging.error(f"Error processing {file_key}: {e}")
                conn.rollback()
                continue

    cursor.close()
    conn.close()

with dag:
    load_to_postgres()
