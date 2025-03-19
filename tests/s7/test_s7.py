from fastapi.testclient import TestClient
from bdi_api.app import app
from bdi_api.s7.exercise import s3_client, get_db_connection

client = TestClient(app)

class TestS7Student:
    """
    Use this class to create tests for your S7 application.
    These tests ensure your code meets the business requirements.
    """

    def test_prepare_data(self) -> None:
        """
        Test the /aircraft/prepare endpoint to ensure data is fetched from S3 and inserted into PostgreSQL.
        """
        response = client.post("/api/s7/aircraft/prepare")
        assert response.status_code == 200, "Prepare endpoint failed"
        assert "Data successfully inserted into PostgreSQL!" in response.text, "Unexpected response message"

    def test_list_aircraft(self) -> None:
        """
        Test the /aircraft/ endpoint to ensure it returns a list of aircraft.
        """
        response = client.get("/api/s7/aircraft?num_results=2&page=0")
        assert response.status_code == 200, "Aircraft list endpoint failed"
        r = response.json()
        assert isinstance(r, list), "Result is not a list"
        assert len(r) <= 2, "Result exceeds num_results limit"
        if len(r) > 0:
            for field in ["icao", "registration", "type"]:
                assert field in r[0], f"Missing '{field}' field in aircraft data"

    def test_aircraft_positions(self) -> None:
        """
        Test the /aircraft/{icao}/positions endpoint to ensure it returns position data for a given ICAO.
        """
        icao = "06a0af"  # Usamos un ICAO de ejemplo como en S1
        response = client.get(f"/api/s7/aircraft/{icao}/positions?num_results=2&page=0")
        assert response.status_code == 200, "Positions endpoint failed"
        r = response.json()
        assert isinstance(r, list), "Result is not a list"
        assert len(r) <= 2, "Result exceeds num_results limit"
        if len(r) > 0:
            for field in ["timestamp", "lat", "lon"]:
                assert field in r[0], f"Missing '{field}' field in position data"


class TestItCanBeEvaluated:
    """
    These tests ensure the S7 exercise can be evaluated.
    Do not modify anything here!
    Make sure all tests pass with `poetry run pytest` or it will be a 0!
    """

    def test_prepare(self) -> None:
        response = client.post("/api/s7/aircraft/prepare")
        assert not response.is_error, "Error at the prepare endpoint"
        assert "Data successfully inserted into PostgreSQL!" in response.text, "Prepare endpoint did not complete successfully"

    def test_aircraft(self) -> None:
        response = client.get("/api/s7/aircraft")
        assert not response.is_error, "Error at the aircraft endpoint"
        r = response.json()
        assert isinstance(r, list), "Result is not a list"
        assert len(r) > 0, "Result is empty"
        for field in ["icao", "registration", "type"]:
            assert field in r[0], f"Missing '{field}' field."

    def test_positions(self) -> None:
        icao = "06a0af"
        response = client.get(f"/api/s7/aircraft/{icao}/positions")
        assert not response.is_error, "Error at the positions endpoint"
        r = response.json()
        assert isinstance(r, list), "Result is not a list"
        assert len(r) > 0, "Result is empty"
        for field in ["timestamp", "lat", "lon"]:
            assert field in r[0], f"Missing '{field}' field."