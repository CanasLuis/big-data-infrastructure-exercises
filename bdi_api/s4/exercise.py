from concurrent.futures import ThreadPoolExecutor
import logging
import os
import gzip
import shutil
from typing import Annotated
from urllib.parse import urljoin
import json

import requests
from bs4 import BeautifulSoup
import pandas as pd
from tqdm import tqdm
import boto3
from fastapi import APIRouter, status
from fastapi.params import Query
from io import BytesIO

from bdi_api.settings import Settings


settings = Settings()

# Crear el cliente para AWS S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=settings.s3_key_id,
    aws_secret_access_key=settings.s3_access_key,
    aws_session_token=settings.s3_session_token,
    region_name=settings.s3_region
)

s4 = APIRouter(
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Not found"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "Something is wrong with the request"},
    },
    prefix="/api/s4",
    tags=["s4"],
)

# Modificación del endpoint de descarga para guardar archivos .json.gz
@s4.post("/aircraft/download")
def download_data(
    file_limit: Annotated[
        int,
        Query(
            ...,
            description="""Limits the number of files to download.
            You must always start from the first the page returns and
            go in ascending order in order to correctly obtain the results.
            I'll test with increasing number of files starting from 100.""",
        ),
    ] = 100,
) -> str:
    """Download JSON files from source and store in S3 as compressed JSON files (.json.gz)."""
    base_url = settings.source_url + "/2023/11/01/"
    s3_bucket = settings.s3_bucket
    s3_prefix_path = "raw/day=20231101/"

    download_dir = os.path.join(settings.raw_dir, "day=20231101")
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir, exist_ok=True)

    try:
        response = requests.get(base_url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        files = [a["href"] for a in soup.find_all("a") if a["href"].endswith(".json.gz")][:file_limit]

        def fetch_file(file_name):
            file_url = urljoin(base_url, file_name)
            file_path = os.path.join(download_dir, file_name)
            response = requests.get(file_url, stream=True)
            if response.status_code == 200:
                with gzip.open(file_path, "wb") as f:
                    f.write(response.content)

        with ThreadPoolExecutor(max_workers=5) as executor:
            list(tqdm(executor.map(fetch_file, files), total=len(files), desc="Downloading files"))

    except requests.RequestException as e:
        logging.error(f"Error accessing URL: {str(e)}")
        return f"Error accessing URL: {str(e)}"

    # Subida a S3
    all_files = []
    for root, _, files in os.walk(download_dir):
        for file in files:
            local_file_path = os.path.join(root, file)
            relative_path = os.path.relpath(local_file_path, download_dir)
            s3_object_name = os.path.join(s3_prefix_path, relative_path).replace("\\", "/")
            all_files.append((local_file_path, s3_object_name))

    for local_file_path, s3_object_name in tqdm(all_files, desc="Uploading files", unit="file"):
        try:
            s3_client.upload_file(local_file_path, s3_bucket, s3_object_name)
        except Exception as e:
            logging.error(f"Failed to upload {local_file_path}: {e}")
            return f"Failed to upload {local_file_path}: {e}"

    return "OK"


# Modificación del endpoint de preparación para unificar en un solo archivo JSON normal (sin comprimir) en S3
@s4.post("/aircraft/prepare")
def prepare_data() -> str:
    """Obtain all aircraft data from raw JSON files and save them into a single cleaned JSON file in S3 (without compression)."""
    raw_folder = os.path.join(settings.raw_dir, "day=20231101")
    prepared_folder = os.path.join(settings.prepared_dir, "day=20231101")

    # Verificar si la carpeta preparada existe, si no, crearla
    if os.path.exists(prepared_folder):
        shutil.rmtree(prepared_folder)
    os.makedirs(prepared_folder, exist_ok=True)

    if not os.path.exists(raw_folder) or not os.listdir(raw_folder):
        logging.error(f"No raw data found in {raw_folder}")
        fake_json_path = os.path.join(raw_folder, "fake.json")
        with open(fake_json_path, "w") as f:
            json.dump({"aircraft": []}, f)

    all_aircraft_data = []

    # Procesar todos los archivos JSON
    for file in os.listdir(raw_folder):
        if file.endswith(".json.gz"):
            file_path = os.path.join(raw_folder, file)
            try:
                with gzip.open(file_path, "rt") as f:
                    file_data = json.load(f)

                # Extraer datos de cada avión
                aircraft_data = [
                    {
                        "icao": aircraft.get("hex"),
                        "registration": aircraft.get("r"),
                        "type": aircraft.get("t"),
                        "latitude": aircraft.get("lat"),
                        "longitude": aircraft.get("lon"),
                        "alt_baro": aircraft.get("alt_baro", None),
                        "gs": aircraft.get("gs", None),
                        "emergency": aircraft.get("emergency", False),
                        "timestamp": file_data.get("now"),
                    }
                    for aircraft in file_data.get("aircraft", [])
                    if aircraft.get("hex") and aircraft.get("lat") and aircraft.get("lon")
                ]

                if not aircraft_data:
                    logging.warning(f"No aircraft data found in {file}")
                    continue

                all_aircraft_data.extend(aircraft_data)

            except Exception as e:
                logging.warning(f"Failed to process file {file}: {e}")

    if not all_aircraft_data:
        logging.error("No valid aircraft data found.")
        return "No valid data found."

    # Guardar todos los datos en un único archivo JSON normal
    merged_file_path = os.path.join(prepared_folder, "merged_aircraft_data.json")
    with open(merged_file_path, "w", encoding="utf-8") as f:
        json.dump({"aircraft": all_aircraft_data}, f)

    # Subir el archivo JSON normal a S3
    s3_object_name = "prepared/day=20231101/merged_aircraft_data.json"
    try:
        s3_client.upload_file(merged_file_path, settings.s3_bucket, s3_object_name)
    except Exception as e:
        logging.error(f"Failed to upload {merged_file_path}: {e}")
        return f"Failed to upload {merged_file_path}: {e}"

    return f"Data preparation completed successfully! Single JSON file saved in S3 at {s3_object_name}"

# En `exercise.py`, al final, deberías agregar lo siguiente:

from fastapi import FastAPI
from bdi_api.s4.exercise import s4  # Esto importa correctamente el router `s4` desde `exercise.py`

app = FastAPI()

# Incluir el router de s4 correctamente
app.include_router(s4)
