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
    PE = "pe"
    READ = "read"
    KB = "kb"
    DEV = "dev"
    ORCHESTRATOR = "orchestrator"
    SYSTEM = "system"


class RoomKind(str, Enum):
    OPS = "ops"
    TASK = "task"
    ENGG = "engg"
    MEMORY = "memory"
    WAVE = "wave"
    GENERAL = "general"


class TaskKind(str, Enum):
    INIT = "init"
    BUG = "bug"
    ENHANCEMENT = "enhancement"
    ISSUE = "issue"


class TaskState(str, Enum):
    BOUND = "bound"
    RUNNING = "running"
    GATED = "gated"
    DONE = "done"
    HALTED = "halted"
    ARCHIVED = "archived"


class TaskSource(str, Enum):
    BUZZ = "buzz"
    GITHUB = "github"


class TaskEventKind(str, Enum):
    GATE_OPEN = "gate_open"
    GOD_TAKEN = "god_taken"
    GOD_HALT = "god_halt"
    BATON = "baton"
    LAND = "land"
    ARCHIVE = "archive"
    DELETE = "delete"
    INGRESS = "ingress"
    STATE = "state"
    REWIND = "rewind"
    REWIND_DENIED = "rewind_denied"


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


class MessagePage(BaseCreateModel):
    """Cursor page of room messages (chronological ascending)."""

    items: list[MessageRead] = Field(default_factory=list)
    has_more: bool = False


class TaskCreate(BaseCreateModel):
    tenant_slug: str = Field(..., min_length=1, max_length=64)
    kind: TaskKind
    task_id: str = Field(..., min_length=2, max_length=128)
    title: str = Field(..., min_length=1, max_length=512)
    source: TaskSource = TaskSource.BUZZ
    source_ref: Optional[str] = Field(default=None, max_length=512)
    hub_room_slug: str = Field(..., min_length=2, max_length=128)
    state: TaskState = TaskState.BOUND


class TaskRead(BasePostgresModel):
    tenant_slug: str
    kind: TaskKind
    task_id: str
    title: str
    state: TaskState
    source: TaskSource
    source_ref: Optional[str] = None
    hub_room_slug: str
    task_room_slug: str
    archived_at: Optional[datetime] = None
    archived_by: Optional[str] = None


class RoomMemberCreate(BaseCreateModel):
    room_slug: str = Field(..., min_length=2, max_length=128)
    identity_handle: str = Field(..., min_length=2, max_length=128)
    member_role: str = Field(default="participant", max_length=64)


class RoomMemberRead(BasePostgresModel):
    room_id: UUID
    identity_id: UUID
    identity_handle: str = ""
    identity_display_name: str = ""
    member_role: str = "participant"


class RoomRosterEntry(BaseCreateModel):
    """Member + live presence for desktop listening strip."""

    identity_handle: str
    identity_display_name: str = ""
    member_role: str = "participant"
    presence: Optional[str] = None  # listening | busy | None (offline)


class TaskEventCreate(BaseCreateModel):
    tenant_slug: str = Field(..., min_length=1, max_length=64)
    task_id: str = Field(..., min_length=2, max_length=128)
    kind: TaskEventKind
    role_id: str = Field(default="", max_length=128)
    purpose: str = Field(default="", max_length=128)
    token: str = Field(default="", max_length=256)
    evidence_ref: str = Field(default="", max_length=1024)
    payload: Optional[dict[str, Any]] = None


class TaskEventRead(BasePostgresModel):
    tenant_slug: str
    task_id: str
    seq: int
    kind: TaskEventKind
    role_id: str = ""
    purpose: str = ""
    token: str = ""
    evidence_ref: str = ""
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
