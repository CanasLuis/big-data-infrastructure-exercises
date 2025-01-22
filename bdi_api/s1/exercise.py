import os
import requests
import pandas as pd
import json
import logging
from tqdm import tqdm
from typing import Annotated
from bs4 import BeautifulSoup 

from fastapi import APIRouter, status
from fastapi.params import Query
from urllib.parse import urljoin
from bdi_api.settings import Settings

settings = Settings()

s1 = APIRouter( #the assignments are isolated in routers
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Not found"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "Something is wrong with the request"},
    },
    prefix="/api/s1", #application called postman(API client) #GET, #POST, #UPDATE
    tags=["s1"],
)


@s1.post("/aircraft/download") #endpoint --> prefix is the router
def download_data(
    file_limit: Annotated[
        int,
        Query(
            ...,
            description="""
    Limits the number of files to download.
    You must always start from the first the page returns and
    go in ascending order in order to correctly obtain the results.
    I'll test with increasing number of files starting from 100.""",
        ),
    ] = 100,
) -> str:
    """Downloads the file_limit files AS IS inside the folder data/20231101

    data: https://samples.adsbexchange.com/readsb-hist/2023/11/01/
    documentation: https://www.adsbexchange.com/version-2-api-wip/
        See "Trace File Fields" section

    Think about the way you organize the information inside the folder
    and the level of preprocessing you might need.

    To manipulate the data use any library you feel comfortable with.
    Just make sure to configure it in the pyproject.toml file
    so it can be installed using poetry update.


    TIP: always clean the download folder before writing again to avoid having old files.
    """
    download_dir = os.path.join(settings.raw_dir, "day=20231101")
    base_url = settings.source_url + "/2023/11/01/"
    # TODO Implement download

    # Create directory if it doesn't exist
    os.makedirs(download_dir, exist_ok=True)

    # Limpieza de la carpeta de descargas
    for file in os.listdir(download_dir):
        file_path = os.path.join(download_dir, file)
        if os.path.isfile(file_path): 
            os.remove(file_path)


    try:
        # Get list of files from the URL
        response = requests.get(base_url)
        response.raise_for_status()  # Added error handling for HTTP status
        
        soup = BeautifulSoup(response.text, 'html.parser')
        files = [
            a['href'] for a in soup.find_all('a') 
            if a['href'].endswith('.json.gz')
        ][:file_limit]  # Apply the file limit
        
        downloaded_count = 0
        for file_name in tqdm(files, desc="Downloading files"):
            file_url = urljoin(base_url, file_name)
            response = requests.get(file_url, stream=True)
            
            if response.status_code == 200:
                file_path = os.path.join(download_dir, file_name[:-3])
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                downloaded_count += 1
            else:
                print(f"Failed to download {file_name}")

        
        return f"Downloaded {downloaded_count} files to {download_dir}"
    
    except requests.RequestException as e:
        return f"Error accessing URL: {str(e)}"
    except Exception as e:
        return f"Error during download: {str(e)}"


    
@s1.post("/aircraft/prepare")
def prepare_data() -> str:
    """Prepare the data in the way you think it's better for the analysis.

    * data: https://samples.adsbexchange.com/readsb-hist/2023/11/01/
    * documentation: https://www.adsbexchange.com/version-2-api-wip/
        See "Trace File Fields" section

    Think about the way you organize the information inside the folder
    and the level of preprocessing you might need.

    To manipulate the data use any library you feel comfortable with.
    Just make sure to configure it in the `pyproject.toml` file
    so it can be installed using `poetry update`.

    TIP: always clean the prepared folder before writing again to avoid having old files.

    Keep in mind that we are downloading a lot of small files, and some libraries might not work well with this!
    """
    try:
        # Define input (raw data) and output (prepared data) folders
        raw_folder = os.path.join(settings.raw_dir, "day=20231101")
        prepared_folder = os.path.join(settings.prepared_dir, "day=20231101")

        # Ensure the output directory exists
        os.makedirs(prepared_folder, exist_ok=True)

        # Clean old files in the prepared folder
        for file in os.listdir(prepared_folder):
            file_path = os.path.join(prepared_folder, file)
            if os.path.isfile(file_path):
                os.remove(file_path)

        # Process each JSON file individually and save as a separate CSV
        for file in os.listdir(raw_folder):
            if file.endswith(".json"):
                file_path = os.path.join(raw_folder, file)
                try:
                    with open(file_path, "r") as f:
                        file_data = json.load(f)
                        # Extract the "aircraft" array and required fields
                        aircraft_data = [
                            {
                                "icao": aircraft.get("hex"),
                                "registration": aircraft.get("r"),
                                "type": aircraft.get("t"),
                                "latitude": aircraft.get("lat"),
                                "longitude": aircraft.get("lon"),
                                "timestamp": file_data.get("now")
                            }
                            for aircraft in file_data.get("aircraft", [])
                        ]

                        # Verify that there is data to write
                        if not aircraft_data:
                            logging.warning(f"No aircraft data found in file {file}")
                            continue

                        # Convert to DataFrame
                        df = pd.DataFrame(aircraft_data)

                        # Drop rows with missing or empty data in any of the required columns
                        df = df.dropna(subset=["icao", "registration", "type", "latitude", "longitude", "timestamp"])

                        # Save to a CSV file named after the JSON file
                        output_csv = os.path.join(prepared_folder, f"{os.path.splitext(file)[0]}.csv")
                        df.to_csv(output_csv, index=False)

                except Exception as e:
                    logging.warning(f"Failed to process file {file}: {e}")

        return f"Data preparation completed successfully! CSV files saved in {prepared_folder}"

    except Exception as e:
        logging.error(f"Error in prepare_data: {e}")
        return f"Data preparation failed: {str(e)}"

@s1.get("/aircraft/")
def list_aircraft(num_results: int = 100, page: int = 0) -> list[dict]:
    """List all the available aircraft, its registration and type ordered by
    icao asc
    """
    try:
        # Define the folder where prepared CSV files are located
        prepared_folder = os.path.join(settings.prepared_dir, "day=20231101")

        # Check if the folder exists
        if not os.path.exists(prepared_folder):
            logging.warning(f"Prepared folder {prepared_folder} does not exist.")
            return []  # Return an empty list if no data is available

        # Get the list of files in the folder
        csv_files = [file for file in os.listdir(prepared_folder) if file.endswith(".csv")]

        # Check if the requested page exists
        if page >= len(csv_files):
            logging.warning(f"Page {page} does not exist. Total available files: {len(csv_files)}.")
            return []  # Return an empty list if the page does not exist

        # Load the specific CSV file for the requested page
        file_path = os.path.join(prepared_folder, csv_files[page])
        try:
            df = pd.read_csv(file_path)
            # Ensure required columns exist
            if not {"icao", "registration", "type", "latitude", "longitude", "timestamp"}.issubset(df.columns):
                logging.warning(f"CSV file {csv_files[page]} is missing required columns.")
                return []

            # Sort data by ICAO and timestamp
            df.sort_values(by=["icao", "timestamp"], inplace=True)

            # DEBUG: Log the structure of the DataFrame to ensure it's correct
            logging.debug(f"DataFrame content:\n{df}")

            # Get the first `num_results` rows
            result_data = df.head(num_results)

            # DEBUG: Log the extracted rows for verification
            logging.debug(f"Selected rows (first {num_results}):\n{result_data}")

            # Convert the DataFrame to a list of dictionaries
            return result_data.to_dict(orient="records")

        except Exception as e:
            logging.error(f"Failed to read file {csv_files[page]}: {e}")
            return []

    except Exception as e:
        # Log the error and return an empty list
        logging.error(f"Error in list_aircraft: {e}")
        return []
    


@s1.get("/aircraft/{icao}/positions")
def get_aircraft_position(icao: str, num_results: int = 1000, page: int = 0) -> list[dict]:
    """Returns all the known positions of an aircraft ordered by time (asc)
    If an aircraft is not found, return an empty list.
    """
    try:
        # Define the folder where prepared CSV files are stored
        prepared_folder = os.path.join(settings.prepared_dir, "day=20231101")

        # Check if the folder exists
        if not os.path.exists(prepared_folder):
            logging.warning(f"Prepared folder {prepared_folder} does not exist.")
            return []  # Return an empty list if no data is available

        # Initialize a list to collect positions
        positions = []

        # Iterate over all CSV files in the folder
        for file in os.listdir(prepared_folder):
            if file.endswith(".csv"):
                file_path = os.path.join(prepared_folder, file)
                try:
                    # Load the CSV file
                    df = pd.read_csv(file_path)

                    # Log the structure of the DataFrame
                    logging.info(f"Processing file: {file}, Rows: {len(df)}")

                    # Ensure required columns exist
                    required_columns = {"icao", "timestamp", "latitude", "longitude"}
                    if not required_columns.issubset(df.columns):
                        logging.warning(f"File {file} is missing required columns.")
                        continue

                    # Filter rows matching the specified ICAO
                    filtered_rows = df[df["icao"] == icao]
                    if filtered_rows.empty:
                        logging.info(f"No matching rows for ICAO {icao} in file {file}")
                    else:
                        logging.info(f"Found {len(filtered_rows)} matching rows in file {file}")

                    # Add the filtered rows to the positions list
                    for _, row in filtered_rows.iterrows():
                        positions.append({
                            "timestamp": row["timestamp"],
                            "lat": row["latitude"],
                            "lon": row["longitude"],
                        })

                except Exception as e:
                    logging.error(f"Error processing file {file}: {e}")

        # If no positions were found, return an empty list
        if not positions:
            logging.info(f"No positions found for ICAO {icao} in any file.")
            return []

        # Sort the positions by timestamp
        positions.sort(key=lambda x: x["timestamp"])

        # Paginate the results
        start_index = page * num_results
        end_index = start_index + num_results
        paginated_positions = positions[start_index:end_index]

        # Log the results before returning
        logging.info(f"Returning {len(paginated_positions)} positions for ICAO {icao}.")
        return paginated_positions

    except Exception as e:
        logging.error(f"Error in get_aircraft_position: {e}")
        return []


@s1.get("/aircraft/{icao}/stats")
def get_aircraft_statistics(icao: str) -> dict:
    """Returns different statistics about the aircraft

    * max_altitude_baro
    * max_ground_speed
    * had_emergency
    """
    try:
        # Define the folder where prepared CSV files are stored
        prepared_folder = os.path.join(settings.prepared_dir, "day=20231101")

        # Check if the folder exists
        if not os.path.exists(prepared_folder):
            logging.warning(f"Prepared folder {prepared_folder} does not exist.")
            return {
                "max_altitude_baro": None,
                "max_ground_speed": None,
                "had_emergency": None
            }

        # Initialize variables for statistics
        max_altitude_baro = None
        max_ground_speed = None
        had_emergency = False

        # Iterate through all CSV files
        for file in os.listdir(prepared_folder):
            if file.endswith(".csv"):
                file_path = os.path.join(prepared_folder, file)
                try:
                    # Load the CSV file
                    df = pd.read_csv(file_path)

                    # Log the file and its rows
                    logging.info(f"Processing file: {file}, Total rows: {len(df)}")

                    # Ensure required columns exist
                    required_columns = {"icao", "alt_baro", "gs", "emergency"}
                    if not required_columns.issubset(df.columns):
                        logging.warning(f"File {file} is missing required columns: {required_columns - set(df.columns)}")
                        continue

                    # Filter rows where `icao` matches
                    filtered_rows = df[df["icao"] == icao]
                    if filtered_rows.empty:
                        logging.info(f"No matching rows for ICAO {icao} in file {file}")
                        continue

                    # Update statistics
                    max_altitude_baro = max(max_altitude_baro or 0, filtered_rows["alt_baro"].max())
                    max_ground_speed = max(max_ground_speed or 0, filtered_rows["gs"].max())
                    had_emergency = had_emergency or filtered_rows["emergency"].any()

                except Exception as e:
                    logging.error(f"Error processing file {file}: {e}")

        # Return statistics
        return {
            "max_altitude_baro": max_altitude_baro,
            "max_ground_speed": max_ground_speed,
            "had_emergency": had_emergency
        }

    except Exception as e:
        logging.error(f"Error in get_aircraft_statistics: {e}")
        return {
            "max_altitude_baro": None,
            "max_ground_speed": None,
            "had_emergency": None
        }
