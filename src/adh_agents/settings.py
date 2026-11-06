"""Per-agent settings base — progress ticks and role identity."""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from src.configs.base_settings import BaseSettings


class AgentSettings(BaseSettings):
    """Shared knobs every responsibility agent may override via its own PREFIX."""

    PREFIX: ClassVar[str] = "ADH_AGENT"

    role_id: str = Field(default="adh.agent", description="Buzz identity handle")
    progress_seconds: float = Field(
        default=60.0,
        ge=0.05,
        description="Seconds between Buzz still-working posts during long work",
    )
    wait_steps: int = Field(
        default=30,
        ge=1,
        le=120,
        description="Max progress ticks before warning / fail policy",
    )
    baton_ttl_seconds: int = Field(
        default=86400,
        ge=60,
        description="Redis baton key TTL",
    )


class PmAgentSettings(AgentSettings):
    """PM lane agent settings (Team OS). Lane knobs still live on HermesSettings."""

    PREFIX: ClassVar[str] = "ADH_PM"

    role_id: str = Field(default="adh.pm")
    progress_seconds: float = Field(default=60.0, ge=0.05)
    wait_steps: int = Field(default=30, ge=1, le=120)
    emit_pe_review_baton: bool = Field(
        default=True,
        description="After open_draft_pr success, emit pe.review baton (Wave 0a; PE consumes in 0b)",
    )
