"""Hermes API tests with the service mocked."""

from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_hermes_service
from src.models.hermes_models import HermesArtifactRead


def _override(client: TestClient, hermes: MagicMock) -> None:
    cast(FastAPI, client.app).dependency_overrides[get_hermes_service] = lambda: hermes


def test_pm_brief(client: TestClient) -> None:
    hermes = MagicMock()
    hermes.run_pm_brief = AsyncMock(
        return_value=HermesArtifactRead(
            id=uuid4(),
            kind="pm_brief",
            initiative="INIT-ADH-000",
            rubric_id="rubric-pm",
            overall=2.1,
            body="PM brief INIT-ADH-000",
            payload={"lane": "pm"},
            model="glm",
        )
    )
    _override(client, hermes)
    response = client.post("/api/v1/hermes/pm/brief", json={"initiative": "INIT-ADH-000"})
    assert response.status_code == 201
    assert response.json()["kind"] == "pm_brief"


def test_eng_grade(client: TestClient) -> None:
    hermes = MagicMock()
    hermes.run_eng_grade = AsyncMock(
        return_value=HermesArtifactRead(
            id=uuid4(),
            kind="eng_grade",
            initiative="INIT-ADH-000",
            rubric_id="rubric-eng",
            overall=1.8,
            recommend_merge="no",
            body="do not merge",
            payload={"pr_ref": "demo/INIT-ADH-000-g0-fixture"},
            model="glm",
        )
    )
    _override(client, hermes)
    response = client.post("/api/v1/hermes/eng/grade", json={"pr_ref": "demo/x", "verify_exit": 0})
    assert response.status_code == 201
    assert response.json()["recommend_merge"] == "no"


def test_list_ledger(client: TestClient) -> None:
    hermes = MagicMock()
    hermes.list_ledger = AsyncMock(return_value=[])
    _override(client, hermes)
    response = client.get("/api/v1/hermes/ledger")
    assert response.status_code == 200
    assert response.json() == []
