"""PmHttpLanes HTTP API smoke tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from typing import cast

from src.api.dependencies import get_pm_http_lanes
from src.models.hermes_models import HermesArtifactRead


def test_pm_brief(client, lanes=None):
    lanes = AsyncMock()
    lanes.run_pm_brief = AsyncMock(
        return_value=HermesArtifactRead(
            kind="pm_brief",
            initiative="INIT-ADH-000",
            rubric_id="pm",
            body="ok",
            payload={},
        )
    )
    cast(FastAPI, client.app).dependency_overrides[get_pm_http_lanes] = lambda: lanes
    response = client.post("/api/v1/hermes/pm/brief", json={"initiative": "INIT-ADH-000"})
    assert response.status_code == 201


def test_eng_grade(client):
    lanes = AsyncMock()
    lanes.run_eng_grade = AsyncMock(
        return_value=HermesArtifactRead(
            kind="eng_grade",
            initiative="INIT-ADH-000",
            rubric_id="eng",
            body="ok",
            payload={},
        )
    )
    cast(FastAPI, client.app).dependency_overrides[get_pm_http_lanes] = lambda: lanes
    response = client.post("/api/v1/hermes/eng/grade", json={"pr_ref": "demo/x", "verify_exit": 0})
    assert response.status_code == 201


def test_ledger(client):
    lanes = AsyncMock()
    lanes.list_ledger = AsyncMock(return_value=[])
    cast(FastAPI, client.app).dependency_overrides[get_pm_http_lanes] = lambda: lanes
    response = client.get("/api/v1/hermes/ledger")
    assert response.status_code == 200
