"""Minimal health API test."""

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    """Health endpoint returns status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "ok"
