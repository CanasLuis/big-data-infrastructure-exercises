import json
import logging
import os

import boto3
import psycopg
from fastapi import APIRouter, FastAPI, HTTPException, status  # Añadimos FastAPI

from bdi_api.settings import DBCredentials, Settings

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load settings and credentials
settings = Settings()
db_credentials = DBCredentials()

# AWS S3 session
session = boto3.Session(
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
    region_name=os.getenv("AWS_REGION", "us-east-1"),
)

logger.info(f"AWS_ACCESS_KEY_ID={os.getenv('AWS_ACCESS_KEY_ID')}")
logger.info(f"AWS_SECRET_ACCESS_KEY={os.getenv('AWS_SECRET_ACCESS_KEY')}")
logger.info(f"AWS_SESSION_TOKEN={os.getenv('AWS_SESSION_TOKEN')}")

s3_client = session.client("s3")

# FastAPI Router
s7 = APIRouter(
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Not found"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "Invalid request"},
    },
    prefix="/api/s7",
    tags=["s7"],
)

# Crear la aplicación FastAPI y añadir el router
app = FastAPI()
app.include_router(s7)

# Database connection function
def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    try:
        conn = psycopg.connect(
            host=db_credentials.DB_HOST,
            dbname=db_credentials.DB_NAME,
            user=db_credentials.DB_USER,
            password=db_credentials.DB_PASSWORD,
            port=db_credentials.DB_PORT,
            autocommit=True,
        )
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed") from e

# Ensure table exists
def create_table():
    """Creates the aircraft_positions table if it doesn't exist."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS aircraft_positions (
                        id SERIAL PRIMARY KEY,
                        icao TEXT NOT NULL,
                        registration TEXT,
                        type TEXT,
                        latitude DOUBLE PRECISION,
                        longitude DOUBLE PRECISION,
                        alt_baro DOUBLE PRECISION,
                        gs DOUBLE PRECISION,
                        emergency BOOLEAN DEFAULT FALSE,
                        timestamp DOUBLE PRECISION NOT NULL
                    );
                """)
                conn.commit()
                logger.info("Table 'aircraft_positions' verified.")
    except Exception as e:
        logger.error(f"Error creating/verifying table: {e}")

@s7.post("/aircraft/prepare")
def prepare_data():
    """Fetch raw aircraft data from S3, process it, and insert into PostgreSQL."""
    s3_bucket = settings.s3_bucket
    s3_key = "prepared/day=20231101/merged_aircraft_data.json"

    logger.info(f"Fetching data from S3 bucket: {s3_bucket}")

    try:
        # Fetch data from S3
        s3_response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
        raw_data = json.loads(s3_response['Body'].read().decode("utf-8"))

        # Ensure table exists
        create_table()

        # Insert data into PostgreSQL
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for aircraft in raw_data.get("aircraft", []):
                    try:
                        cur.execute("""
                            INSERT INTO aircraft_positions (
                                icao, registration, type, latitude, longitude,
                                alt_baro, gs, emergency, timestamp
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (icao, timestamp) DO NOTHING;
                        """, (
                            aircraft.get("icao"),
                            aircraft.get("registration"),
                            aircraft.get("type"),
                            aircraft.get("latitude"),
                            aircraft.get("longitude"),
                            aircraft.get("alt_baro"),
                            aircraft.get("gs"),
                            aircraft.get("emergency") if isinstance(aircraft.get("emergency"), bool) else False,
                            aircraft.get("timestamp")
                        ))
                    except Exception as e:
                        logger.error(f"Error inserting data: {e}")
                conn.commit()

        return "Data successfully inserted into PostgreSQL!"

    except Exception as e:
        logger.error(f"Error processing data from S3: {e}")
        return {"error": str(e)}

@s7.get("/aircraft/")
def list_aircraft(num_results: int = 100, page: int = 0):
    """List available aircraft with registration and type from the database."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                offset = num_results * page
                cur.execute("""
                    SELECT icao, registration, type
                    FROM aircraft_positions
                    ORDER BY icao ASC
                    LIMIT %s OFFSET %s;
                """, (num_results, offset))
                data = cur.fetchall()

        return [{"icao": row[0], "registration": row[1], "type": row[2]} for row in data]

    except Exception as e:
        logger.error(f"Error retrieving aircraft list: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve aircraft data") from e

@s7.get("/aircraft/{icao}/positions")
def get_aircraft_position(icao: str, num_results: int = 1000, page: int = 0):
    """Retrieve known positions of an aircraft ordered by time (asc) from the database."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                offset = num_results * page
                cur.execute("""
                    SELECT timestamp, latitude, longitude
                    FROM aircraft_positions
                    WHERE icao = %s
                    ORDER BY timestamp ASC
                    LIMIT %s OFFSET %s;
                """, (icao, num_results, offset))
                data = cur.fetchall()

        return [{"timestamp": row[0], "lat": row[1], "lon": row[2]} for row in data]

    except Exception as e:
        logger.error(f"Error retrieving positions for aircraft {icao}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve aircraft positions") from e

@s7.get("/aircraft/{icao}/stats")
def get_aircraft_statistics(icao: str):
    """Retrieve aircraft statistics from the database."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT MAX(alt_baro), MAX(gs), BOOL_OR(emergency)
                    FROM aircraft_positions
                    WHERE icao = %s;
                """, (icao,))
                data = cur.fetchone()

        if not data or data[0] is None:
            return {"error": "Aircraft not found"}

        return {
            "max_altitude_baro": data[0],
            "max_ground_speed": data[1],
            "had_emergency": data[2]
        }

    except Exception as e:
        logger.error(f"Error retrieving statistics for aircraft {icao}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve aircraft statistics") from e
