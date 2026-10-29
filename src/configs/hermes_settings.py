"""Hermes brain settings — LiteLLM plus hermes/ledger databases."""

from typing import ClassVar

from pydantic import Field, SecretStr

from src.configs.base_settings import BaseSettings


class HermesSettings(BaseSettings):
    """Runtime knobs for the Hermes PM + after-PR lanes."""

    PREFIX: ClassVar[str] = "HERMES"

    litellm_base_url: str = Field(
        default="http://localhost:4000/v1",
        description="OpenAI-compatible LiteLLM base URL",
    )
    litellm_api_key: str = Field(
        default="sk-adh-local-master",
        description="LiteLLM master key",
    )
    model: str = Field(
        default="qwen", description="Fallback LiteLLM alias when lane model is unset"
    )
    pm_model: str = Field(
        default="",
        description="LiteLLM alias for PM think/ready/brief. Empty uses model.",
    )
    eng_model: str = Field(
        default="",
        description="LiteLLM alias for after-PR grade. Empty uses model.",
    )
    wait_step_seconds: float = Field(
        default=30.0,
        ge=0.05,
        description="Each wait increment while the model runs",
    )
    wait_steps: int = Field(
        default=40,
        ge=1,
        le=80,
        description="How many +wait_step waits before the PM lane fails",
    )
    timeout_seconds: float = Field(
        default=1200.0,
        ge=30.0,
        description="Hard cap; default is wait_step_seconds * wait_steps (covers 20k completion)",
    )
    progress_seconds: float = Field(
        default=30.0,
        ge=0.05,
        description="Alias of wait_step_seconds for still-working posts",
    )

    pg_host: str = Field(default="localhost")
    pg_port: int = Field(default=5432)
    pg_user: str = Field(default="adh")
    pg_password: SecretStr = Field(default=SecretStr("adh"))
    pg_db: str = Field(default="hermes")
    ledger_db: str = Field(default="ledger")

    run_boot_jobs: bool = Field(
        default=False,
        description="On start, run one PM brief and one eng grade if missing",
    )
    listen_ops: bool = Field(
        default=True,
        description="Watch each active tenant {slug}-ops for Lead outlines",
    )
    memory_room: str = Field(default="adh-memory")
    ops_room: str = Field(default="adh-ops")
    lead_handle: str = Field(default="nikd10x")
    outline_min_chars: int = Field(default=60, ge=20)
    outline_lock_seconds: int = Field(
        default=3600,
        ge=60,
        description="Cover think C1 + C2 + quality, each up to wait_budget",
    )
    pm_max_think_runs: int = Field(
        default=4,
        ge=2,
        le=8,
        description="Max new prd-think files per outline. Never overwrite a prior run.",
    )
    pm_max_ready_passes: int = Field(
        default=2,
        ge=1,
        le=4,
        description="Max file-backed ready/quality passes per outline.",
    )
    litellm_concurrency: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Process-wide LiteLLM cap so active tenants cannot stampede the model",
    )
    threshold_x: float = Field(default=2.7, description="Pinned copy of rubric-eng X")

    def model_for_lane(self, lane: str) -> str:
        if lane == "pm":
            return (self.pm_model or self.model or "qwen").strip()
        return (self.eng_model or self.model or "qwen").strip()

    def wait_budget_seconds(self) -> float:
        return float(self.wait_step_seconds) * int(self.wait_steps)
