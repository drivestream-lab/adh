"""HTTP API for the Buzz conversation plane."""

from collections.abc import AsyncIterator
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from src.api.dependencies import get_buzz_service
from src.business_services.buzz_service import BuzzService
from src.logging import get_logger
from src.models.buzz_models import (
    HeartbeatIngest,
    IdentityCreate,
    IdentityRead,
    MessageCreate,
    MessagePage,
    MessageRead,
    RoomCreate,
    RoomMemberCreate,
    RoomMemberRead,
    RoomRead,
    RoomRosterEntry,
    StaleIdentity,
    TaskCreate,
    TaskEventCreate,
    TaskEventRead,
    TaskRead,
)
from src.utils.api_helpers import handle_api_errors

logger = get_logger()
router = APIRouter(prefix="/buzz", tags=["Buzz"])


@router.get("/identities", response_model=list[IdentityRead])
@handle_api_errors("list identities", "Buzz")
async def list_identities(
    buzz: BuzzService = Depends(get_buzz_service),
) -> list[IdentityRead]:
    return await buzz.list_identities()


@router.post("/identities", response_model=IdentityRead, status_code=201)
@handle_api_errors("create identity", "Buzz")
async def create_identity(
    payload: IdentityCreate,
    buzz: BuzzService = Depends(get_buzz_service),
) -> IdentityRead:
    return await buzz.create_identity(payload)


@router.get("/rooms", response_model=list[RoomRead])
@handle_api_errors("list rooms", "Buzz")
async def list_rooms(
    buzz: BuzzService = Depends(get_buzz_service),
) -> list[RoomRead]:
    return await buzz.list_rooms()


@router.post("/rooms", response_model=RoomRead, status_code=201)
@handle_api_errors("create room", "Buzz")
async def create_room(
    payload: RoomCreate,
    buzz: BuzzService = Depends(get_buzz_service),
) -> RoomRead:
    return await buzz.create_room(payload)


@router.get("/rooms/{slug}", response_model=RoomRead)
@handle_api_errors("get room", "Buzz")
async def get_room(
    slug: str,
    buzz: BuzzService = Depends(get_buzz_service),
) -> RoomRead:
    return await buzz.get_room(slug)


@router.get("/rooms/{slug}/messages", response_model=MessagePage)
@handle_api_errors("list messages", "Buzz")
async def list_messages(
    slug: str,
    limit: int = Query(default=20, ge=1, le=500),
    before_id: Optional[UUID] = Query(default=None),
    buzz: BuzzService = Depends(get_buzz_service),
) -> MessagePage:
    return await buzz.list_messages(
        slug,
        limit=limit,
        before_id=str(before_id) if before_id is not None else None,
    )


@router.post("/rooms/{slug}/messages", response_model=MessageRead, status_code=201)
@handle_api_errors("post message", "Buzz")
async def post_message(
    slug: str,
    payload: MessageCreate,
    buzz: BuzzService = Depends(get_buzz_service),
) -> MessageRead:
    return await buzz.post_message(slug, payload)


@router.get("/rooms/{slug}/members", response_model=list[RoomMemberRead])
@handle_api_errors("list room members", "Buzz")
async def list_members(
    slug: str,
    buzz: BuzzService = Depends(get_buzz_service),
) -> list[RoomMemberRead]:
    return await buzz.list_members(slug)


@router.get("/rooms/{slug}/roster", response_model=list[RoomRosterEntry])
@handle_api_errors("list room roster", "Buzz")
async def list_room_roster(
    slug: str,
    buzz: BuzzService = Depends(get_buzz_service),
) -> list[RoomRosterEntry]:
    """Members + live presence for the desktop listening strip."""
    return await buzz.list_room_roster(slug)


@router.post("/rooms/{slug}/members", response_model=RoomMemberRead, status_code=201)
@handle_api_errors("ensure room member", "Buzz")
async def ensure_member(
    slug: str,
    payload: RoomMemberCreate,
    buzz: BuzzService = Depends(get_buzz_service),
) -> RoomMemberRead:
    body = payload.model_copy(update={"room_slug": slug})
    return await buzz.ensure_member(body)


@router.get("/rooms/{slug}/stream")
@handle_api_errors("stream room", "Buzz")
async def stream_room(
    slug: str,
    buzz: BuzzService = Depends(get_buzz_service),
) -> StreamingResponse:
    await buzz.get_room(slug)

    async def events() -> AsyncIterator[str]:
        async for payload in buzz.stream_room(slug):
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/tasks", response_model=TaskRead, status_code=201)
@handle_api_errors("create task", "Buzz")
async def create_task(
    payload: TaskCreate,
    buzz: BuzzService = Depends(get_buzz_service),
) -> TaskRead:
    return await buzz.create_task(payload)


@router.get("/tenants/{tenant_slug}/tasks", response_model=list[TaskRead])
@handle_api_errors("list tasks", "Buzz")
async def list_tasks(
    tenant_slug: str,
    include_archived: bool = Query(default=False),
    buzz: BuzzService = Depends(get_buzz_service),
) -> list[TaskRead]:
    return await buzz.list_tasks(tenant_slug, include_archived=include_archived)


@router.get("/tenants/{tenant_slug}/tasks/{task_id}", response_model=TaskRead)
@handle_api_errors("get task", "Buzz")
async def get_task(
    tenant_slug: str,
    task_id: str,
    buzz: BuzzService = Depends(get_buzz_service),
) -> TaskRead:
    return await buzz.get_task(tenant_slug, task_id)


@router.post(
    "/tenants/{tenant_slug}/tasks/{task_id}/archive",
    response_model=TaskRead,
)
@handle_api_errors("archive task", "Buzz")
async def archive_task(
    tenant_slug: str,
    task_id: str,
    archived_by: str = Query(..., min_length=2),
    buzz: BuzzService = Depends(get_buzz_service),
) -> TaskRead:
    return await buzz.archive_task(tenant_slug, task_id, archived_by=archived_by)


@router.delete("/tenants/{tenant_slug}/tasks/{task_id}", status_code=204)
@handle_api_errors("delete task", "Buzz")
async def delete_task(
    tenant_slug: str,
    task_id: str,
    deleted_by: str = Query(..., min_length=2),
    buzz: BuzzService = Depends(get_buzz_service),
) -> None:
    await buzz.delete_task(tenant_slug, task_id, deleted_by=deleted_by)


@router.get(
    "/tenants/{tenant_slug}/tasks/{task_id}/events",
    response_model=list[TaskEventRead],
)
@handle_api_errors("list task events", "Buzz")
async def list_task_events(
    tenant_slug: str,
    task_id: str,
    buzz: BuzzService = Depends(get_buzz_service),
) -> list[TaskEventRead]:
    return await buzz.list_task_events(tenant_slug, task_id)


@router.post(
    "/tenants/{tenant_slug}/tasks/{task_id}/events",
    response_model=TaskEventRead,
    status_code=201,
)
@handle_api_errors("append task event", "Buzz")
async def append_task_event(
    tenant_slug: str,
    task_id: str,
    payload: TaskEventCreate,
    buzz: BuzzService = Depends(get_buzz_service),
) -> TaskEventRead:
    body = payload.model_copy(update={"tenant_slug": tenant_slug, "task_id": task_id})
    return await buzz.append_task_event(body)


@router.post("/heartbeats", response_model=MessageRead, status_code=201)
@handle_api_errors("ingest heartbeat", "Buzz")
async def ingest_heartbeat(
    payload: HeartbeatIngest,
    buzz: BuzzService = Depends(get_buzz_service),
) -> MessageRead:
    return await buzz.ingest_heartbeat(payload)


@router.get("/heartbeats/stale", response_model=list[StaleIdentity])
@handle_api_errors("list stale heartbeats", "Buzz")
async def list_stale(
    buzz: BuzzService = Depends(get_buzz_service),
) -> list[StaleIdentity]:
    return await buzz.list_stale_identities()
