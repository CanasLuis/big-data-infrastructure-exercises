from airflow import DAG
from airflow.decorators import task
from airflow.utils.dates import days_ago

import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import os
import math


default_args = {
    'owner': 'airflow',
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    dag_id='calculate_fuel_consumption_dag',
    default_args=default_args,
    description='Calculate fuel consumption from aircraft_positions and store in local PostgreSQL',
    schedule_interval=None,
    start_date=datetime(2023, 11, 1),
    catchup=False,
    tags=['fuel', 'postgres']
)

@task()
def calculate_fuel():
    
    postgres_host = os.getenv("POSTGRES_HOST")
    postgres_port = os.getenv("POSTGRES_PORT")
    postgres_db = os.getenv("POSTGRES_DB")
    postgres_user = os.getenv("POSTGRES_USER")
    postgres_password = os.getenv("POSTGRES_PASSWORD")

    if not all([postgres_host, postgres_port, postgres_db, postgres_user, postgres_password]):
        raise ValueError("One or more PostgreSQL environment variables are not defined")

   
    conn = psycopg2.connect(
        host=postgres_host,
        port=postgres_port,
        database=postgres_db,
        user=postgres_user,
        password=postgres_password
    )
    cursor = conn.cursor()

    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fuel_consumption (
            icao VARCHAR(10),
            flight_date DATE,
            distance_km FLOAT,
            fuel_liters FLOAT
        );
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_fuel_consumption_unique
        ON fuel_consumption (icao, flight_date);
    """)
    conn.commit()

    # Load aircraft_positions data
    query = """
    SELECT icao, latitude, longitude, gs, timestamp
    FROM aircraft_positions
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND timestamp IS NOT NULL
    ORDER BY icao, timestamp;
    """
    df = pd.read_sql_query(query, conn)

    if df.empty:
        logging.warning("No data found in aircraft_positions for fuel calculation")
        cursor.close()
        conn.close()
        return

    
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371  # Earth radius in km
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return R * c

    fuel_rate = 3.0  # Liters per km
    fuel_records = []

    
    df['flight_date'] = pd.to_datetime(df['timestamp'], unit='s').dt.date
    for (icao, date), group in df.groupby(['icao', 'flight_date']):
        group = group.sort_values('timestamp')
        total_distance = 0.0

        for i in range(len(group) - 1):
            lat1, lon1 = group.iloc[i][['latitude', 'longitude']]
            lat2, lon2 = group.iloc[i + 1][['latitude', 'longitude']]
            total_distance += haversine(lat1, lon1, lat2, lon2)

        if total_distance > 0:
            fuel_liters = total_distance * fuel_rate
            fuel_records.append((icao, date, total_distance, fuel_liters))

    # Insert data into fuel_consumption table
    if fuel_records:
        insert_query = """
        INSERT INTO fuel_consumption (icao, flight_date, distance_km, fuel_liters)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (icao, flight_date) DO NOTHING;
        """
        cursor.executemany(insert_query, fuel_records)
        conn.commit()
        logging.info(f"Inserted {len(fuel_records)} fuel consumption records")

    cursor.close()
    conn.close()

with dag:
    calculate_fuel()
