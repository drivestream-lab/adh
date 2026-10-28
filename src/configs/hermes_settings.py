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
    model: str = Field(default="qwen", description="LiteLLM model alias")
    timeout_seconds: float = Field(default=90.0)

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
    memory_room: str = Field(default="adh-memory")
    ops_room: str = Field(default="adh-ops")
    threshold_x: float = Field(default=2.7, description="Pinned copy of rubric-eng X")
