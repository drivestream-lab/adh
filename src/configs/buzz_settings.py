"""Buzz conversation-plane settings."""

from typing import ClassVar

from pydantic import Field

from src.configs.base_settings import BaseSettings


class BuzzSettings(BaseSettings):
    """Runtime knobs for the Buzz plane."""

    PREFIX: ClassVar[str] = "BUZZ"

    heartbeat_seconds: int = Field(
        default=90,
        description="Long-running jobs must post progress at least this often",
    )
    seed_on_start: bool = Field(
        default=True,
        description="Ensure default rooms and identities exist on startup",
    )
    publish_system_heartbeat: bool = Field(
        default=True,
        description="adh.system posts a heartbeat to adh-ops on the interval",
    )
