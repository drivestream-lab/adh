"""F1 — MessagePage pagination contract."""

from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_buzz_service
from src.models.buzz_models import MessageKind, MessagePage, MessageRead


def _override(client: TestClient, buzz: MagicMock) -> None:
    cast(FastAPI, client.app).dependency_overrides[get_buzz_service] = lambda: buzz


def test_list_messages_returns_page(client: TestClient) -> None:
    buzz = MagicMock()
    mid = uuid4()
    buzz.list_messages = AsyncMock(
        return_value=MessagePage(
            items=[
                MessageRead(
                    id=mid,
                    room_id=uuid4(),
                    identity_id=uuid4(),
                    identity_handle="adh.pm",
                    identity_display_name="PM",
                    body="hello",
                    kind=MessageKind.MESSAGE,
                )
            ],
            has_more=True,
        )
    )
    _override(client, buzz)
    response = client.get("/api/v1/buzz/rooms/adh-ops/messages?limit=20")
    assert response.status_code == 200
    body = response.json()
    assert body["has_more"] is True
    assert body["items"][0]["body"] == "hello"
    buzz.list_messages.assert_awaited()


def test_list_messages_before_id(client: TestClient) -> None:
    buzz = MagicMock()
    buzz.list_messages = AsyncMock(return_value=MessagePage(items=[], has_more=False))
    _override(client, buzz)
    before = uuid4()
    response = client.get(f"/api/v1/buzz/rooms/adh-ops/messages?limit=20&before_id={before}")
    assert response.status_code == 200
    assert response.json()["has_more"] is False
    assert buzz.list_messages.await_args is not None
    assert str(before) == buzz.list_messages.await_args.kwargs.get("before_id") or str(
        before
    ) in str(buzz.list_messages.await_args)
