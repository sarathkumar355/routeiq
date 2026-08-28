"""Tests for the /health endpoint and basic app startup."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_app_starts():
    """Importing and instantiating the app should not raise."""
    assert app is not None
    assert app.title == "RouteIQ"


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_response_body():
    response = client.get("/health")
    body = response.json()
    assert body == {"status": "healthy"}
