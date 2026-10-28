"""HTTP API for the Buzz conversation plane."""

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_buzz_service
from src.business_services.buzz_service import BuzzService
from src.logging import get_logger
from src.models.buzz_models import (
    HeartbeatIngest,
    IdentityCreate,
    IdentityRead,
    MessageCreate,
    MessageRead,
    RoomCreate,
    RoomRead,
    StaleIdentity,
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


@router.get("/rooms/{slug}/messages", response_model=list[MessageRead])
@handle_api_errors("list messages", "Buzz")
async def list_messages(
    slug: str,
    limit: int = Query(default=200, ge=1, le=500),
    buzz: BuzzService = Depends(get_buzz_service),
) -> list[MessageRead]:
    return await buzz.list_messages(slug, limit=limit)


@router.post("/rooms/{slug}/messages", response_model=MessageRead, status_code=201)
@handle_api_errors("post message", "Buzz")
async def post_message(
    slug: str,
    payload: MessageCreate,
    buzz: BuzzService = Depends(get_buzz_service),
) -> MessageRead:
    return await buzz.post_message(slug, payload)


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
