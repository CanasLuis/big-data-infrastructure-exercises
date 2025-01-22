import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bdi_api.app import app as real_app


@pytest.fixture(scope="class")
def app() -> FastAPI:
    """In case you want to test only a part"""
    return real_app


@pytest.fixture(scope="class")
def client(app: FastAPI) -> TestClient:
    """We include our router for the examples"""
    yield TestClient(app)
