"""Publish PM artifacts into a product meta repo on develop as adh-dev-pm."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from injector import inject

from src.configs.orchestrator_settings import OrchestratorSettings
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.base_infra_service import BaseInfraService
from src.infra_services.github_app_service import GitHubAppService
from src.logging import get_logger
from src.models.orchestrator_models import AppRole
from src.models.tenant_models import TenantContext

logger = get_logger()

_PM_APP_SLUG = "adh-dev-pm"
_INIT_STEM = re.compile(r"^(INIT-[A-Z0-9-]+?)(?:-PRD-THINK(?:-\d+)?|-PRD-QUALITY)?$")


@dataclass
class MetaInventory:
    """T0 listing of INIT ids and think files already on the tenant meta repo."""

    inits: list[str] = field(default_factory=list)
    think_paths: list[str] = field(default_factory=list)
    prd_paths: list[str] = field(default_factory=list)


def think_path(initiative: str, run: int) -> str:
    if run <= 1:
        return f"prd/reports/{initiative}-prd-think.md"
    return f"prd/reports/{initiative}-prd-think-{run}.md"


def next_free_think_runs(initiative: str, existing: list[str]) -> tuple[int, int]:
    occupied = set(existing)
    run = 1
    while True:
        first = think_path(initiative, run)
        second = think_path(initiative, run + 1)
        if first not in occupied and second not in occupied:
            return run, run + 1
        run += 1


_JOB_EMPTY = re.compile(r"\*\*Job:\*\*\s*(\(none\)|\s*$)", re.IGNORECASE | re.MULTILINE)
_JOB_PRESENT = re.compile(r"(?im)(\*\*Job:\*\*|Job to be Done:|## Job\b|Job Statement)")
_CAP_EMPTY = re.compile(r"- CAP-\d+:\s+\(J:", re.IGNORECASE)
_OBS_EMPTY = re.compile(r"→\s*n/a", re.IGNORECASE)
_JOURNEY_PLACEHOLDER = re.compile(r"J-\d+:\s+\S+\s*/\s*\?\s*→\s*\?", re.IGNORECASE)


def skeleton_material_fails(file_body: str) -> list[str]:
    """Code pre-gate: empty job/CAP/observable/journey cannot be engineering-ready."""
    text = file_body or ""
    fails: list[str] = []
    if not _JOB_PRESENT.search(text) and "Job:" not in text:
        fails.append("B1 Job is missing")
    elif _JOB_EMPTY.search(text):
        fails.append("B1 Job is empty")
    if _CAP_EMPTY.search(text):
        fails.append("B2 CAP text is empty")
    if _OBS_EMPTY.search(text):
        fails.append("B3 Observable result is n/a")
    if _JOURNEY_PLACEHOLDER.search(text):
        fails.append("B14 Journeys are placeholders")
    return fails


def next_programme_init(prefix: str, occupied: list[str]) -> str:
    """Next INIT-{COMPONENT}-{NUMBER} from programme.yaml prefix + occupied meta ids.

    COMPONENT is the programme slug. NUMBER is the next unused integer among
    occupied INIT-{COMPONENT}-{n} files (three digits). Job-shaped rest tokens
    are ignored. Does not invent a slug from the outline.
    """
    base = (prefix or "").strip().rstrip("-").upper()
    if not base.startswith("INIT-") or base == "INIT":
        raise ValueError("programme INIT prefix is missing")
    pattern = re.compile(rf"^{re.escape(base)}-(\d+)$")
    highest = 0
    for token in occupied:
        match = pattern.match((token or "").strip().upper())
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{base}-{highest + 1:03d}"


class PmWorkspaceService(BaseInfraService):
    """Writes think/quality files on the tenant integration branch. Never merges."""

    @inject
    def __init__(self, github: GitHubAppService) -> None:
        self._github = github
        self._orch = OrchestratorSettings.get_instance()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        await self._github.initialize()
        self._initialized = True
        pem = self._pem_path()
        logger.info(
            "Initializing PM workspace service",
            pem=str(pem) if pem else "",
            pem_readable=bool(pem and pem.is_file()),
        )

    async def close(self) -> None:
        self._initialized = False

    async def health_check(self) -> bool:
        return self._initialized

    def inventory(self, tenant: TenantContext) -> MetaInventory:
        """Read INIT ids from tenant meta prd/ and prd/reports/. Does not invent ids."""
        root = Path(tenant.meta_root).expanduser()
        inits: set[str] = set()
        think_paths: list[str] = []
        prd_paths: list[str] = []
        for folder, kind in (
            (root / "prd", "prd"),
            (root / "prd" / "reports", "reports"),
        ):
            if not folder.is_dir():
                continue
            for path in sorted(folder.iterdir()):
                if not path.is_file() or path.suffix.lower() != ".md":
                    continue
                initiative = _init_from_filename(path.name)
                if initiative is None:
                    continue
                inits.add(initiative)
                relative = str(path.relative_to(root))
                if kind == "reports" and "-prd-think" in path.name.lower():
                    think_paths.append(relative)
                elif kind == "prd":
                    prd_paths.append(relative)
        return MetaInventory(
            inits=sorted(inits),
            think_paths=think_paths,
            prd_paths=prd_paths,
        )

    async def publish(
        self,
        tenant: TenantContext,
        relative_path: str,
        contents: str,
        commit_message: str,
    ) -> dict[str, Any]:
        """Write the file locally and commit it on the tenant branch as adh-dev-pm."""
        local = self._write_local(tenant, relative_path, contents)
        github = await self._put_github(tenant, relative_path, contents, commit_message)
        if local is None and github is None:
            raise ValidationError(
                f"PM artifact {relative_path} was not written to workspace or GitHub"
            )
        logger.info(
            "Published PM artifact",
            slug=tenant.slug,
            path=relative_path,
            local=str(local) if local else None,
            github_sha=(github or {}).get("commit_sha"),
        )
        return {"local_path": str(local) if local else None, "github": github}

    def _roles_path(self) -> Optional[Path]:
        if self._orch.meta_root:
            path = Path(self._orch.meta_root).expanduser() / "config" / "roles.yaml"
            return path if path.is_file() else None
        if self._orch.workspace_root:
            factory = (
                Path(self._orch.workspace_root).expanduser() / "adh-meta" / "config" / "roles.yaml"
            )
            return factory if factory.is_file() else None
        cwd = Path.cwd()
        for base in (cwd, cwd.parent):
            factory = base / "adh-meta" / "config" / "roles.yaml"
            if factory.is_file():
                return factory
        return None

    def _pem_path(self) -> Optional[Path]:
        roles_path = self._roles_path()
        if roles_path is None:
            return None
        try:
            return Path(_pm_app(roles_path).pem).expanduser()
        except Exception:
            logger.exception("PM GitHub App identity is not readable")
            return None

    def _write_local(
        self, tenant: TenantContext, relative_path: str, contents: str
    ) -> Optional[Path]:
        root = Path(tenant.meta_root).expanduser()
        if not root.exists() and not root.parent.exists():
            logger.warning("PM product meta root missing; skip workspace write", root=str(root))
            return None
        dest = root / relative_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(contents, encoding="utf-8")
        logger.info("Wrote PM artifact to workspace", path=str(dest), slug=tenant.slug)
        return dest

    async def _put_github(
        self,
        tenant: TenantContext,
        relative_path: str,
        contents: str,
        commit_message: str,
    ) -> Optional[dict[str, Any]]:
        roles_path = self._roles_path()
        if roles_path is None:
            logger.warning("roles.yaml missing; skip GitHub publish")
            return None
        app = _pm_app(roles_path)
        if tenant.meta_repo not in app.repos:
            raise ValidationError(
                f"PM write refused: {tenant.meta_repo} is not on identity {_PM_APP_SLUG}"
            )
        try:
            token, granted = await self._github.installation_token(
                app,
                write=True,
                repositories=[tenant.meta_repo],
            )
            logger.info(
                "Minted PM GitHub token",
                app=_PM_APP_SLUG,
                slug=tenant.slug,
                permissions=granted,
            )
            return await self._github.put_text_file(
                token,
                tenant.meta_repo,
                path=relative_path,
                contents=contents,
                branch=tenant.integration_branch,
                message=commit_message,
            )
        except ValidationError:
            raise
        except Exception:
            logger.exception(
                "GitHub publish failed",
                path=relative_path,
                repo=tenant.meta_repo,
                branch=tenant.integration_branch,
                slug=tenant.slug,
            )
            return None


def _init_from_filename(name: str) -> Optional[str]:
    stem = Path(name).stem.upper()
    match = _INIT_STEM.match(stem)
    if match is None:
        return None
    token = match.group(1)
    if not token or "PENDING" in token:
        return None
    return token


def _pm_app(roles_path: Path) -> AppRole:
    with roles_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    apps = (data or {}).get("apps") or {}
    raw = apps.get(_PM_APP_SLUG)
    if not isinstance(raw, dict):
        raise ValidationError(f"roles.yaml missing app {_PM_APP_SLUG}")
    return AppRole.model_validate(raw)
