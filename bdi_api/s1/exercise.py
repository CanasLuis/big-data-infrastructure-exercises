import json
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, status
from fastapi.params import Query
from tqdm import tqdm

from bdi_api.settings import Settings

settings = Settings()

s1 = APIRouter(
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Not found"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "Something is wrong with the request"},
    },
    prefix="/api/s1",
    tags=["s1"],
)

# Parte 1: Endpoint para descargar los archivos
@s1.post("/aircraft/download")
def download_data(
    file_limit: Annotated[int, Query(..., description="Limits the number of files to download.")] = 100,
) -> str:
    download_dir = os.path.join(settings.raw_dir, "day=20231101")
    base_url = settings.source_url + "/2023/11/01/"

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
            file_path = os.path.join(download_dir, file_name[:-3])
            response = requests.get(file_url, stream=True)
            if response.status_code == 200:
                with open(file_path, "wb") as f:
                    f.write(response.content)

        with ThreadPoolExecutor(max_workers=5) as executor:
            list(tqdm(executor.map(fetch_file, files), total=len(files), desc="Downloading files"))

        return f"Downloaded {len(files)} files to {download_dir}"

    except requests.RequestException as e:
        logging.error(f"Error accessing URL: {str(e)}")
        return f"Error accessing URL: {str(e)}"

    finally:
        logging.info("Download attempt completed.")


# Parte 2: Endpoint para preparar y procesar los datos
@s1.post("/aircraft/prepare")
def prepare_data() -> str:
    """Prepares all aircraft data from raw JSON files and saves cleaned CSVs."""
    raw_folder = os.path.join(settings.raw_dir, "day=20231101")
    prepared_folder = os.path.join(settings.prepared_dir, "day=20231101")

    if os.path.exists(prepared_folder):
        shutil.rmtree(prepared_folder)
    os.makedirs(prepared_folder, exist_ok=True)

    if not os.path.exists(raw_folder) or not os.listdir(raw_folder):
        logging.error(f"No raw data found in {raw_folder}")
        fake_json_path = os.path.join(raw_folder, "fake.json")
        with open(fake_json_path, "w") as f:
            json.dump({"aircraft": []}, f)

    for file in os.listdir(raw_folder):
        if file.endswith(".json"):
            file_path = os.path.join(raw_folder, file)
            try:
                with open(file_path) as f:
                    file_data = json.load(f)

                aircraft_data = [
                    {
                        "icao": aircraft.get("hex", "unknown"),
                        "registration": aircraft.get("r", "unknown"),
                        "type": aircraft.get("t", "unknown"),
                        "latitude": aircraft.get("lat", 0.0),
                        "longitude": aircraft.get("lon", 0.0),
                        "alt_baro": aircraft.get("alt_baro", 0),
                        "gs": aircraft.get("gs", 0),
                        "emergency": aircraft.get("emergency", False),
                        "timestamp": file_data.get("now", None),
                    }
                    for aircraft in file_data.get("aircraft", [])
                    if aircraft.get("hex") and aircraft.get("lat") and aircraft.get("lon")
                ]

                if not aircraft_data:
                    logging.warning(f"No aircraft data found in {file}")
                    continue

                df = pd.DataFrame(aircraft_data)
                df.dropna(subset=["icao", "latitude", "longitude", "timestamp"], inplace=True)

                output_csv = os.path.join(prepared_folder, f"{os.path.splitext(file)[0]}.csv")
                df.to_csv(output_csv, index=False)

            except Exception as e:
                logging.warning(f"Failed to process file {file}: {e}")

    return f"Data preparation completed successfully! CSV files saved in {prepared_folder}"


# Parte 3: Endpoint para listar los aviones
@s1.get("/aircraft/")
def list_aircraft(num_results: int = 100, page: int = 0) -> list[dict]:
    prepared_folder = os.path.join(settings.prepared_dir, "day=20231101")

    if not os.path.exists(prepared_folder) or not os.listdir(prepared_folder):
        logging.warning(f"Prepared folder {prepared_folder} does not exist.")
        return []

    all_data = []
    for file in os.listdir(prepared_folder):
        if file.endswith(".csv"):
            file_path = os.path.join(prepared_folder, file)
            df = pd.read_csv(file_path, low_memory=False)
            if {"icao", "registration", "type"}.issubset(df.columns):
                all_data.extend(df.to_dict(orient="records"))

    all_data.sort(key=lambda x: x["icao"])
    start_idx = page * num_results
    return all_data[start_idx : start_idx + num_results]


# Parte 4: Endpoint para obtener las posiciones de un avión
@s1.get("/aircraft/{icao}/positions")
def get_aircraft_position(icao: str, num_results: int = 1000, page: int = 0) -> list[dict]:
    prepared_folder = os.path.join(settings.prepared_dir, "day=20231101")

    if not os.path.exists(prepared_folder):
        logging.warning(f"Prepared folder {prepared_folder} does not exist.")
        return []

    positions = []
    for file in os.listdir(prepared_folder):
        if file.endswith(".csv"):
            file_path = os.path.join(prepared_folder, file)
            try:
                df = pd.read_csv(file_path, low_memory=False)
                if {"icao", "timestamp", "latitude", "longitude"}.issubset(df.columns):
                    filtered_rows = df[df["icao"] == icao]

                    positions.extend(
                        filtered_rows[["timestamp", "latitude", "longitude"]]
                        .sort_values(by="timestamp")
                        .rename(columns={"latitude": "lat", "longitude": "lon"})
                        .to_dict(orient="records")
                    )

            except Exception as e:
                logging.error(f"Error processing file {file}: {e}")

    start_index = page * num_results
    return positions[start_index : start_index + num_results]


# Parte 5: Endpoint para obtener estadísticas del avión
@s1.get("/aircraft/{icao}/stats")
def get_aircraft_statistics(icao: str) -> dict:
    """Returns different statistics about the aircraft"""
    prepared_folder = os.path.join(settings.prepared_dir, "day=20231101")

    if not os.path.exists(prepared_folder):
        logging.warning(f"Prepared folder {prepared_folder} does not exist.")
        return {
            "max_altitude_baro": 0,
            "max_ground_speed": 0,
            "had_emergency": False,
        }

    icao = icao.lower()
    max_altitude_baro = 0
    max_ground_speed = 0
    had_emergency = False

    for file in os.listdir(prepared_folder):
        if file.endswith(".csv"):
            file_path = os.path.join(prepared_folder, file)
            try:
                df = pd.read_csv(file_path, dtype={"icao": str})
                df["icao"] = df["icao"].astype(str).str.lower().str.strip()
                df.fillna(0, inplace=True)

                filtered_rows = df[df["icao"] == icao]

                if not filtered_rows.empty:
                    max_altitude_baro = float(filtered_rows["alt_baro"].max())
                    max_ground_speed = float(filtered_rows["gs"].max())
                    had_emergency = bool(filtered_rows["emergency"].any())

            except Exception as e:
                logging.error(f"Error processing file {file}: {e}")

    return {
        "max_altitude_baro": max_altitude_baro,
        "max_ground_speed": max_ground_speed,
        "had_emergency": had_emergency,
    }

