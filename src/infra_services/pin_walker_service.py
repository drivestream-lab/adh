"""Deterministic pin + roles walker. No LLM on the control path."""

from pathlib import Path
from typing import Optional

import yaml

from src.configs.orchestrator_settings import OrchestratorSettings
from src.exceptions.app_exceptions import NotFoundError, ValidationError
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger
from src.models.orchestrator_models import AppRole, PinDocument, PinWave, RolesDocument

logger = get_logger()

_ROLE_TO_APP = {
    "backend": "adh-dev-backend",
    "frontend": "adh-dev-frontend",
    "pm": "adh-dev-pm",
    "reviewer": "adh-reviewer",
}


def parse_pin(data: object) -> PinDocument:
    if not isinstance(data, dict):
        raise ValidationError("pin is not a mapping")
    return PinDocument.model_validate(data)


def parse_roles(data: object) -> RolesDocument:
    if not isinstance(data, dict):
        raise ValidationError("roles is not a mapping")
    return RolesDocument.model_validate(data)


def app_slug_for_role(role: str) -> str:
    try:
        return _ROLE_TO_APP[role]
    except KeyError as exc:
        raise ValidationError(f"unknown spawn role {role}") from exc


class PinWalkerService(BaseInfraService):
    """Reads adh-meta pin.yaml and roles.yaml. Never calls a model."""

    def __init__(self) -> None:
        self._settings = OrchestratorSettings.get_instance()
        self._pin: Optional[PinDocument] = None
        self._roles: Optional[RolesDocument] = None
        self._initialized = False

    def workspace_root(self) -> Path:
        if self._settings.workspace_root:
            return Path(self._settings.workspace_root).expanduser().resolve()
        cwd = Path.cwd()
        if cwd.name == "adh":
            return cwd.parent
        if (cwd / "adh").is_dir():
            return cwd
        return cwd

    def meta_root(self) -> Path:
        if self._settings.meta_root:
            return Path(self._settings.meta_root).expanduser().resolve()
        return self.workspace_root() / "adh-meta"

    def repo_path(self, repo: str) -> Path:
        return self.workspace_root() / repo

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._pin = parse_pin(_read_yaml(self.meta_root() / "config" / "pin.yaml"))
        self._roles = parse_roles(_read_yaml(self.meta_root() / "config" / "roles.yaml"))
        self._initialized = True
        logger.info(
            "Pin walker loaded",
            initiative=self._pin.initiative,
            next_wave=self._pin.next.id if self._pin.next else None,
            allow_merge=self._pin.allow_merge,
        )

    async def close(self) -> None:
        self._initialized = False
        self._pin = None
        self._roles = None

    async def health_check(self) -> bool:
        return self._initialized and self._pin is not None

    def pin(self) -> PinDocument:
        if self._pin is None:
            raise ValidationError("pin walker has not been initialized")
        return self._pin

    def roles(self) -> RolesDocument:
        if self._roles is None:
            raise ValidationError("pin walker has not been initialized")
        return self._roles

    def next_wave(self) -> PinWave:
        pin = self.pin()
        if pin.next is None:
            raise NotFoundError("pin wave", "next")
        return pin.next

    def app_for_wave(self, wave: PinWave) -> tuple[str, AppRole]:
        slug = app_slug_for_role(wave.role)
        try:
            app = self.roles().apps[slug]
        except KeyError as exc:
            raise ValidationError(f"roles.yaml missing app {slug}") from exc
        policy = self.roles().spawn
        if policy.refuse_repo_not_on_identity and wave.repo not in app.repos:
            raise ValidationError(
                f"spawn refused: repo {wave.repo} is not on identity {slug}",
            )
        if policy.cannot_merge and app.merge:
            raise ValidationError(f"spawn refused: identity {slug} has merge=true")
        return slug, app


def _read_yaml(path: Path) -> object:
    if not path.is_file():
        raise NotFoundError("pin file", str(path))
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)
