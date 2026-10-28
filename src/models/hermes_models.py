"""Pydantic models for Hermes PM and after-PR lanes."""

from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from src.models.base_models import BaseCreateModel, BasePostgresModel


class HermesBriefRequest(BaseCreateModel):
    initiative: str = Field(default="INIT-ADH-000", min_length=3, max_length=128)


class HermesGradeRequest(BaseCreateModel):
    pr_ref: str = Field(default="demo/INIT-ADH-000-g0-fixture", min_length=3, max_length=256)
    verify_exit: int = Field(default=0)
    notes: str = Field(default="Synthetic G0 fixture — RealWorld compose is Phase G.")


class HermesArtifactRead(BasePostgresModel):
    kind: str
    initiative: str
    rubric_id: str
    overall: Optional[float] = None
    recommend_merge: Optional[str] = None
    body: str
    payload: dict[str, Any]
    buzz_message_id: Optional[UUID] = None
    model: Optional[str] = None
