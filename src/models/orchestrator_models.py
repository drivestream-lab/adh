"""Pydantic models for the pin walker and Cursor spawn."""

from typing import Any, Optional

from pydantic import ConfigDict, Field

from src.models.base_models import BaseCreateModel


class PinCap(BaseCreateModel):
    cursor: int = Field(default=2, ge=1)
    verify: int = Field(default=1, ge=0)


class PinWave(BaseCreateModel):
    id: str = Field(..., min_length=1, max_length=128)
    role: str = Field(..., min_length=2, max_length=64)
    repo: str = Field(..., min_length=1, max_length=128)
    action: str = Field(default="spawn_coder")
    mode: str = Field(default="ask")
    write: bool = Field(default=False)
    prompt: str = Field(..., min_length=1)


class PinDocument(BaseCreateModel):
    model_config = ConfigDict(
        validate_assignment=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
        extra="ignore",
    )

    initiative: str = Field(..., min_length=3, max_length=128)
    allow_merge: bool = False
    checkpoint_stop: bool = True
    threshold_x: float = 2.7
    cap: PinCap = Field(default_factory=PinCap)
    next: Optional[PinWave] = None


class AppRole(BaseCreateModel):
    model_config = ConfigDict(
        validate_assignment=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
        extra="ignore",
    )

    app_id: int
    installation_id: Optional[int] = None
    pem: str
    repos: list[str] = Field(default_factory=list)
    used_by: str = ""
    merge: bool = False


class SpawnPolicy(BaseCreateModel):
    refuse_repo_not_on_identity: bool = True
    one_repo_per_run: bool = True
    cannot_merge: bool = True


class RolesDocument(BaseCreateModel):
    model_config = ConfigDict(
        validate_assignment=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
        extra="ignore",
    )

    apps: dict[str, AppRole]
    spawn: SpawnPolicy = Field(default_factory=SpawnPolicy)


class SpawnRequest(BaseCreateModel):
    """Optional override. Empty body walks the pin as-is."""

    wave_id: Optional[str] = None


class MergeRequest(BaseCreateModel):
    pr_url: str = Field(default="", max_length=512)


class SpawnResult(BaseCreateModel):
    wave_id: str
    role: str
    repo: str
    identity_handle: str
    app_slug: str
    model: Optional[str] = None
    exit_code: int = 0
    merged: bool = False
    cannot_merge: bool = True
    token_permissions: dict[str, Any] = Field(default_factory=dict)
    buzz_message_ids: list[str] = Field(default_factory=list)
    output_preview: str = ""
