"""Versioned baton + rollup envelopes for agent collaboration."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


BATON_VERSION = "1"


class BatonStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    EXPIRED = "expired"


class Baton(BaseModel):
    """Typed handoff between agents (Redis SSOT for claim; Buzz for human-visible notice)."""

    version: str = Field(default=BATON_VERSION)
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str = Field(description="e.g. pe.review, read.walk, qa.verify")
    from_role: str
    to_role: str
    tenant: str
    ops_room: str
    initiative: str = ""
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    status: BatonStatus = BatonStatus.PENDING
    payload: dict[str, Any] = Field(default_factory=dict)
    artefact_refs: list[str] = Field(default_factory=list)
    idempotency_key: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    claimed_by: Optional[str] = None
    error: Optional[str] = None

    def redis_key(self, *, prefix: str = "adh:baton") -> str:
        key = self.idempotency_key or self.id
        return f"{prefix}:{self.tenant}:{key}"


class Rollup(BaseModel):
    """Short result envelope; heavy evidence lives in artefact_refs."""

    version: str = Field(default=BATON_VERSION)
    baton_id: str
    role: str
    status: BatonStatus
    summary: str = ""
    artefact_refs: list[str] = Field(default_factory=list)
    correlation_id: str = ""
    error: Optional[str] = None
    tools_used: list[str] = Field(default_factory=list)
