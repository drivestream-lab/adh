"""Where YAML prompt templates are loaded from."""

from pathlib import Path
from typing import ClassVar

from pydantic import Field

from src.configs.base_settings import BaseSettings


class PromptSettings(BaseSettings):
    """Root directory for prompt YAML. Empty = src/prompts."""

    PREFIX: ClassVar[str] = "PROMPT"

    root: str = Field(
        default="",
        description="Directory of prompt YAML files. Empty = packaged src/prompts",
    )

    def templates_root(self) -> Path:
        if self.root:
            return Path(self.root).expanduser().resolve()
        return Path(__file__).resolve().parents[1] / "prompts"
