"""Buzz API tests with the service mocked."""

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_buzz_service
from src.models.buzz_models import (
    EventType,
    IdentityKind,
    IdentityRead,
    IdentityRole,
    MessageKind,
    MessageRead,
    RoomKind,
    RoomRead,
)


def _override(client: TestClient, buzz: MagicMock) -> None:
    cast(FastAPI, client.app).dependency_overrides[get_buzz_service] = lambda: buzz


def test_list_rooms(client: TestClient) -> None:
    buzz = MagicMock()
    buzz.list_rooms = AsyncMock(
        return_value=[
            RoomRead(id=uuid4(), slug="adh-ops", title="ADH ops", kind=RoomKind.OPS),
        ]
    )
    _override(client, buzz)
    response = client.get("/api/v1/buzz/rooms")
    assert response.status_code == 200
    assert response.json()[0]["slug"] == "adh-ops"


def test_ingest_heartbeat(client: TestClient) -> None:
    buzz = MagicMock()
    ident_id = uuid4()
    room_id = uuid4()
    buzz.ingest_heartbeat = AsyncMock(
        return_value=MessageRead(
            id=uuid4(),
            room_id=room_id,
            identity_id=ident_id,
            identity_handle="adh.system",
            identity_display_name="Buzz system",
            body="alive",
            kind=MessageKind.HEARTBEAT,
            event_type=EventType.PROGRESS,
        )
    )
    _override(client, buzz)
    response = client.post(
        "/api/v1/buzz/heartbeats",
        json={"identity_handle": "adh.system", "room_slug": "adh-ops", "body": "alive"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "heartbeat"
    assert body["identity_handle"] == "adh.system"


def test_stream_room_closes_pubsub_when_subscribe_fails() -> None:
    from src.business_services.buzz_service import BuzzService

    redis = MagicMock()
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock(side_effect=ConnectionError("Too many connections"))
    pubsub.unsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()
    redis.pubsub.return_value = pubsub
    buzz = BuzzService(MagicMock(), redis, MagicMock())
    buzz.get_room = AsyncMock()

    async def _run() -> None:
        gen = buzz.stream_room("realworld-ops")
        try:
            with pytest.raises(ConnectionError, match="Too many"):
                await anext(gen)
        finally:
            await gen.aclose()

    asyncio.run(_run())
    pubsub.aclose.assert_awaited()


def test_list_identities(client: TestClient) -> None:
    buzz = MagicMock()
    buzz.list_identities = AsyncMock(
        return_value=[
            IdentityRead(
                id=uuid4(),
                handle="nikd10x",
                display_name="Lead",
                kind=IdentityKind.HUMAN,
                role=IdentityRole.LEAD,
            )
        ]
    )
    _override(client, buzz)
    response = client.get("/api/v1/buzz/identities")
    assert response.status_code == 200
    assert response.json()[0]["handle"] == "nikd10x"
