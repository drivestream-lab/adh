"""Orchestrator API tests with the service mocked."""

from typing import cast
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_orchestrator_service
from src.models.orchestrator_models import PinCap, PinDocument, PinWave, SpawnResult


def _override(client: TestClient, orch: MagicMock) -> None:
    cast(FastAPI, client.app).dependency_overrides[get_orchestrator_service] = lambda: orch


def test_read_pin(client: TestClient) -> None:
    orch = MagicMock()
    orch.pin = AsyncMock(
        return_value=PinDocument(
            initiative="INIT-ADH-000",
            allow_merge=False,
            next=PinWave(id="g0-dummy", role="backend", repo="adh", prompt="stop"),
            cap=PinCap(),
        )
    )
    _override(client, orch)
    response = client.get("/api/v1/orchestrator/pin")
    assert response.status_code == 200
    assert response.json()["allow_merge"] is False


def test_spawn_disabled_in_api(client: TestClient) -> None:
    orch = MagicMock()
    orch.spawn_next = AsyncMock(
        return_value=SpawnResult(
            wave_id="g0-dummy",
            role="backend",
            repo="adh",
            identity_handle="adh.coder.adh",
            app_slug="adh-dev-backend",
        )
    )
    _override(client, orch)
    response = client.post("/api/v1/orchestrator/spawn")
    assert response.status_code == 503


def test_merge_checkpoint(client: TestClient) -> None:
    from src.exceptions.app_exceptions import ValidationError

    orch = MagicMock()
    orch.merge_wave = AsyncMock(side_effect=ValidationError("checkpoint stop: no merge"))
    _override(client, orch)
    response = client.post("/api/v1/orchestrator/merge", json={"pr_url": "x"})
    assert response.status_code == 400
    assert "checkpoint" in response.json()["detail"]
