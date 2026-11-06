"""Agent work session — one Redis document per (tenant, role, work_id)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.hermes.intent_models import JudgmentRequest

AWAITING_NONE = "none"
AWAITING_CLARIFY = "clarify"
AWAITING_JUDGMENT = "judgment"
AWAITING_AUTHORIZATION = "authorization"
_AWAITING_VALUES = (AWAITING_NONE, AWAITING_CLARIFY, AWAITING_JUDGMENT, AWAITING_AUTHORIZATION)

UNBOUND_WORK_ID = "__unbound__"

# Known programme ids (open string so new roles register without enum churn).
PROGRAMME_AUTHORING = "authoring"
PROGRAMME_META_PM = "meta-pm"
PROGRAMME_PE = "pe"
PROGRAMME_READ = "read"
PROGRAMME_KB = "kb"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AgentWorkSession(BaseModel):
    """What one role agent is waiting on for one work unit (catalogue stage ids)."""

    model_config = ConfigDict(extra="forbid")

    tenant_slug: str = Field(..., min_length=1)
    role_id: str = Field(..., min_length=1, description="Buzz role that owns this work")
    room: str = Field(..., min_length=1)
    work_id: str = Field(
        default=UNBOUND_WORK_ID,
        description="Primary key part: initiative id, baton correlation, or __unbound__",
    )
    initiative: Optional[str] = Field(
        default=None,
        description="Delivery initiative when bound (from tenant.init_prefix)",
    )
    stage: str = Field(default="", description="Workflow node id (catalogue string)")
    awaiting: str = Field(
        default=AWAITING_NONE,
        description="none|clarify|judgment|authorization",
    )
    open_brief: Optional[JudgmentRequest] = Field(
        default=None,
        description="Brief awaiting Lead reply (judgment or authorization)",
    )
    handoff_outcome: Optional[str] = Field(
        default=None,
        description="Last outcome or Lead reply token recorded on this session",
    )
    slots: dict[str, str] = Field(default_factory=dict)
    programme: Optional[str] = Field(
        default=None,
        description="Registered programme id that owns routing for this work unit",
    )
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("awaiting")
    @classmethod
    def _awaiting_known(cls, value: str) -> str:
        if value not in _AWAITING_VALUES:
            raise ValueError(f"awaiting must be one of {_AWAITING_VALUES}, got {value!r}")
        return value

    def touch(self) -> None:
        self.updated_at = _utcnow()

    def bind_initiative(self, initiative: str) -> None:
        init = initiative.strip().upper()
        self.initiative = init
        self.work_id = init
