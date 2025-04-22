from airflow import DAG
from airflow.decorators import task
from airflow.utils.dates import days_ago

import boto3
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timedelta
import logging

# Default DAG arguments
default_args = {
    'owner': 'airflow',
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    dag_id='download_readsb_data_dag',
    default_args=default_args,
    description='Download readsb-hist JSON.gz files for 20231101 and store in S3 RAW',
    schedule_interval=None,  
    start_date=datetime(2023, 11, 1),
    catchup=False,
    tags=['download', 'readsb']
)

@task()
def download_files():
    bucket = "bdi-aircraft-luis-canas"  
    base_url = "https://samples.adsbexchange.com/readsb-hist/"  
    day = "2023/11/01"  
    day_s3 = "20231101"  

    raw_prefix = f"raw/day={day_s3}/"
    url = urljoin(base_url, day + "/")

    logging.info(f"Fetching file list from {url}")
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Error accessing URL for day {day}: {str(e)}")
        raise

    soup = BeautifulSoup(response.text, "html.parser")
    files = [a["href"] for a in soup.find_all("a") if a["href"].endswith(".json.gz")][:100]  

    s3 = boto3.client("s3")

    for file_name in files:
        try:
            s3_key = f"{raw_prefix}{file_name}"
            file_url = urljoin(url, file_name)

            
            try:
                s3.head_object(Bucket=bucket, Key=s3_key)
                logging.info(f"File {s3_key} already exists in S3. Skipping.")
                continue
            except s3.exceptions.ClientError:
                pass

            logging.info(f"Downloading {file_url}")
            response = requests.get(file_url, stream=True)
            if response.status_code == 200:
                s3.upload_fileobj(response.raw, bucket, s3_key)
                logging.info(f"Uploaded {s3_key} to S3")
            else:
                logging.warning(f"Failed to download {file_url}: Status {response.status_code}")
        except Exception as e:
            logging.error(f"Error downloading {file_url}: {e}")
            raise

with dag:
    download_files()