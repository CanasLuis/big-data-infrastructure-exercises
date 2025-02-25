from fastapi.testclient import TestClient
from bdi_api.s4.exercise import app

client = TestClient(app)

def test_download_data():
    response = client.post("/api/s4/aircraft/download?file_limit=1")
    assert response.status_code == 200
    assert "OK" in response.text

def test_prepare_data():
    response = client.post("/api/s4/aircraft/prepare")
    assert response.status_code == 200
    assert "Data preparation completed successfully!" in response.text
