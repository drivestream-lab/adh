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
    work_ttl_seconds: int = Field(
        default=604800,
        ge=60,
        description="Redis agent work-session TTL (Lead gates; default 7d)",
    )
    presence_ttl_seconds: int = Field(
        default=120,
        ge=30,
        description="Redis presence heartbeat TTL while worker is listening",
    )
    network_retry_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Transient network retries before stall-keep",
    )
    network_retry_backoff_seconds: float = Field(
        default=2.0,
        ge=0.1,
        description="Base backoff seconds between network retries",
    )


class PmAgentSettings(AgentSettings):
    """PM lane agent settings (Team OS)."""

    PREFIX: ClassVar[str] = "ADH_PM"

    role_id: str = Field(default="adh.pm")
    progress_seconds: float = Field(default=60.0, ge=0.05)
    wait_steps: int = Field(default=30, ge=1, le=120)
    emit_pe_review_baton: bool = Field(
        default=True,
        description="After open_draft_pr success, emit pe.review baton",
    )


class PeAgentSettings(AgentSettings):
    PREFIX: ClassVar[str] = "ADH_PE"
    role_id: str = Field(default="adh.pe")
    max_product_questions: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Gate‑1 open product-question cap per round",
    )
    max_question_rounds: int = Field(
        default=2,
        ge=1,
        le=8,
        description="Max PE↔PM agent clarification rounds before settle (U6 default 2)",
    )
    reviewer_app_slug: str = Field(
        default="adh-reviewer",
        description="roles.yaml app used for PE comment + attest",
    )


class ReadAgentSettings(AgentSettings):
    PREFIX: ClassVar[str] = "ADH_READ"
    role_id: str = Field(default="adh.read")


class KbAgentSettings(AgentSettings):
    PREFIX: ClassVar[str] = "ADH_KB"
    role_id: str = Field(default="adh.kb")
    reviewer_app_slug: str = Field(
        default="adh-reviewer",
        description=(
            "roles.yaml app that APPROVEs knowledge docs PRs before land "
            "(branch protection; no PE attest on knowledge lane)"
        ),
    )


class AdhAutonomySettings(BaseSettings):
    """Process-wide autonomy mode (all role workers read the same env)."""

    PREFIX: ClassVar[str] = "ADH"

    autonomy_mode: str = Field(
        default="human",
        description="human | god — god plays brief.recommend through GateOpener",
    )
    god_allow_discard: bool = Field(
        default=False,
        description="When true, god may auto-play destructive discard local",
    )
    god_chain_cap: int = Field(
        default=12,
        ge=1,
        le=40,
        description="Max auto-takes per initiative in one god chain",
    )
