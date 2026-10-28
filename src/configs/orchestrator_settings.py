"""Host orchestrator settings — pin walker, Cursor CLI, GitHub Apps, Buzz HTTP."""

from typing import ClassVar

from pydantic import Field

from src.configs.base_settings import BaseSettings


class OrchestratorSettings(BaseSettings):
    """Runtime knobs for the host-side pin walker and Cursor spawn."""

    PREFIX: ClassVar[str] = "ORCH"

    workspace_root: str = Field(
        default="",
        description="Parent of adh / adh-meta. Empty = infer from cwd",
    )
    meta_root: str = Field(
        default="", description="Path to adh-meta. Empty = workspace_root/adh-meta"
    )
    buzz_base_url: str = Field(default="http://localhost:8080")
    ops_room: str = Field(default="adh-ops")
    cursor_bin: str = Field(default="agent")
    cursor_timeout_seconds: float = Field(default=180.0)
    heartbeat_seconds: float = Field(default=90.0)
    max_cursor: int = Field(default=2)
    github_api: str = Field(default="https://api.github.com")
    github_org: str = Field(default="drivestream-lab")
    enable_spawn: bool = Field(
        default=False,
        description="HTTP spawn is host-only. CLI spawn ignores this and always runs",
    )
