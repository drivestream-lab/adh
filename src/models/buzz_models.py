"""Pydantic models for the Buzz conversation plane."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from src.models.base_models import BaseCreateModel, BasePostgresModel


class IdentityKind(str, Enum):
    HUMAN = "human"
    AGENT = "agent"


class IdentityRole(str, Enum):
    LEAD = "lead"
    CODER = "coder"
    REVIEWER = "reviewer"
    PM = "pm"
    ORCHESTRATOR = "orchestrator"
    SYSTEM = "system"


class RoomKind(str, Enum):
    OPS = "ops"
    MEMORY = "memory"
    WAVE = "wave"
    GENERAL = "general"


class MessageKind(str, Enum):
    MESSAGE = "message"
    HEARTBEAT = "heartbeat"
    EVENT = "event"


class EventType(str, Enum):
    START = "start"
    PROGRESS = "progress"
    STALL = "stall"
    DONE = "done"


class IdentityCreate(BaseCreateModel):
    handle: str = Field(..., min_length=2, max_length=128, examples=["adh.coder.adh"])
    display_name: str = Field(..., min_length=1, max_length=256)
    kind: IdentityKind
    role: IdentityRole


class IdentityRead(BasePostgresModel):
    handle: str
    display_name: str
    kind: IdentityKind
    role: IdentityRole


class RoomCreate(BaseCreateModel):
    slug: str = Field(..., min_length=2, max_length=128, examples=["adh-ops"])
    title: str = Field(..., min_length=1, max_length=256)
    kind: RoomKind = RoomKind.GENERAL


class RoomRead(BasePostgresModel):
    slug: str
    title: str
    kind: RoomKind


class MessageCreate(BaseCreateModel):
    identity_handle: str = Field(..., min_length=2, max_length=128)
    body: str = Field(..., min_length=1)
    kind: MessageKind = MessageKind.MESSAGE
    event_type: Optional[EventType] = None
    payload: Optional[dict[str, Any]] = None


class MessageRead(BasePostgresModel):
    room_id: UUID
    identity_id: UUID
    identity_handle: str = ""
    identity_display_name: str = ""
    body: str
    kind: MessageKind
    event_type: Optional[EventType] = None
    payload: Optional[dict[str, Any]] = None


class HeartbeatIngest(BaseCreateModel):
    identity_handle: str = Field(..., min_length=2, max_length=128)
    room_slug: str = Field(default="adh-ops")
    body: str = Field(default="alive")
    event_type: EventType = EventType.PROGRESS
    payload: Optional[dict[str, Any]] = None


class StaleIdentity(BasePostgresModel):
    handle: str
    display_name: str
    last_heartbeat_at: Optional[datetime] = None
    stale_seconds: Optional[float] = None
