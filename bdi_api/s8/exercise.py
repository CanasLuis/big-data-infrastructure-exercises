from typing import Optional

from fastapi import APIRouter, status, HTTPException
from pydantic import BaseModel
import json
from pathlib import Path

# Initialize FastAPI Router for s8 API endpoints
s8 = APIRouter(
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Not found"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "Something is wrong with the request"},
    },
    prefix="/api/s8",
    tags=["s8"],
)

# Pydantic model for returning aircraft information
class AircraftReturn(BaseModel):
    icao: str
    registration: Optional[str] = None
    type: Optional[str] = None
    owner: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None

# Pydantic model for CO2 calculation result
class AircraftCO2(BaseModel):
    icao: str
    hours_flown: float
    co2: Optional[float] = None

# Load aircraft fuel consumption rates from JSON file
file_path = Path(__file__).parent / "aircraft_type_fuel_consumption_rates.json"
try:
    with open(file_path, "r") as f:
        AIRCRAFT_DATA = json.load(f)
except FileNotFoundError:
    AIRCRAFT_DATA = {}
    print("⚠️ JSON file not found at", file_path)

# Endpoint to list aircraft from the JSON data
@s8.get("/aircraft/")
def list_aircraft(num_results: int = 100, page: int = 0) -> list[AircraftReturn]:
    if not AIRCRAFT_DATA:
        raise HTTPException(status_code=500, detail="Aircraft data not loaded")

    aircraft_list = list(AIRCRAFT_DATA.items())
    start = num_results * page
    end = start + num_results
    results = []
    for icao_code, data in aircraft_list[start:end]:
        results.append(
            AircraftReturn(
                icao=icao_code,
                registration=None,
                type=icao_code,
                owner=None,
                manufacturer=data.get("name"),
                model=data.get("category")
            )
        )
    return results

# Endpoint to calculate CO2 emissions based on aircraft type and day
@s8.get("/aircraft/{icao}/co2")
def get_aircraft_co2(icao: str, day: str) -> AircraftCO2:
    from datetime import datetime

    try:
        day_dt = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="day must be in YYYY-MM-DD format")

    # Dummy simulation of hours flown
    hours_flown = 2.0  # In real use, should come from flight logs in DB or other source

    type_code = icao
    if not type_code or type_code not in AIRCRAFT_DATA:
        return AircraftCO2(icao=icao, hours_flown=hours_flown, co2=None)

    galph = AIRCRAFT_DATA[type_code].get("galph")
    if galph is None:
        return AircraftCO2(icao=icao, hours_flown=hours_flown, co2=None)

    fuel_used_kg = galph * hours_flown * 3.04
    co2_tons = (fuel_used_kg * 3.15) / 907.185

    return AircraftCO2(icao=icao, hours_flown=round(hours_flown, 2), co2=round(co2_tons, 2))
