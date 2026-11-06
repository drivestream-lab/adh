"""Hermes collaborator session — one Redis document per tenant."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.hermes.intent_models import JudgmentRequest

AWAITING_NONE = "none"
AWAITING_CLARIFY = "clarify"
AWAITING_JUDGMENT = "judgment"
AWAITING_AUTHORIZATION = "authorization"
_AWAITING_VALUES = (AWAITING_NONE, AWAITING_CLARIFY, AWAITING_JUDGMENT, AWAITING_AUTHORIZATION)


class HermesProgrammeType(str, Enum):
    """Closed set of Hermes programmes that own a tenant session."""

    AUTHORING = "authoring"
    META_PM = "meta-pm"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class HermesSession(BaseModel):
    """What Hermes is waiting on for one tenant (stage ids come from the catalogue)."""

    model_config = ConfigDict(extra="forbid")

    tenant_slug: str = Field(..., min_length=1)
    room: str = Field(..., min_length=1)
    initiative: Optional[str] = Field(
        default=None, description="Programme initiative id once bound (from tenant.init_prefix)"
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
    programme: Optional[HermesProgrammeType] = Field(
        default=None,
        description="Active Hermes programme that owns Lead routing for this tenant",
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
