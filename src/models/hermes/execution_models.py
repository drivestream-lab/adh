"""Execute-phase DTOs: skill runs and forge actions."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.models.orchestrator_models import AppRole


class SkillRunResult(BaseModel):
    """Outcome of a PM skill run in the tenant meta workspace."""

    model_config = ConfigDict(extra="ignore")

    skill: str = Field(..., min_length=1)
    ok: bool
    exit_code: int
    output: str = Field(default="")
    model: Optional[str] = None


class ForgeActionRequest(BaseModel):
    """Caller-supplied inputs for one forge action (action id itself comes from the catalogue)."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    app: AppRole
    repo: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    body_path: str = Field(..., min_length=1)
    head_branch: str = Field(..., min_length=1)
    draft: bool = True
    labels: list[str] = Field(default_factory=list)


class ForgeActionResult(BaseModel):
    """Result of a forge action."""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(..., min_length=1)
    repo: str = Field(..., min_length=1)
    pr_number: Optional[int] = None
    url: Optional[str] = None
