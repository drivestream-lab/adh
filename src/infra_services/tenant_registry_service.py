"""Load active product tenants from factory tenants.yaml and each programme meta."""

from pathlib import Path
from typing import Optional

import yaml
from injector import inject

from src.configs.orchestrator_settings import OrchestratorSettings
from src.exceptions.app_exceptions import NotFoundError, ValidationError
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger
from src.models.tenant_models import TenantContext, TenantEntry, TenantsDocument

logger = get_logger()

_FACTORY_SLUG = "adh"
_FACTORY_REPOS = frozenset({"adh", "adh-meta", "adh-iac-local"})
_PM_APP_SLUG = "adh-dev-pm"


class TenantRegistryService(BaseInfraService):
    """Activation list in adh-meta; topology always from the tenant programme meta."""

    @inject
    def __init__(self) -> None:
        self._settings = OrchestratorSettings.get_instance()
        self._active: list[TenantContext] = []
        self._document: Optional[TenantsDocument] = None
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

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._document = _load_tenants(self.meta_root() / "config" / "tenants.yaml")
        self._active = [_load_tenant(self, entry) for entry in _active_entries(self._document)]
        self._doctor_roles()
        self._initialized = True
        logger.info(
            "Tenant registry loaded",
            active=[tenant.slug for tenant in self._active],
            count=len(self._active),
            max_active=self._document.max_active,
        )

    async def close(self) -> None:
        self._initialized = False
        self._active = []
        self._document = None

    async def health_check(self) -> bool:
        return self._initialized

    def active(self) -> list[TenantContext]:
        return list(self._active)

    def by_ops_room(self, room: str) -> Optional[TenantContext]:
        for tenant in self._active:
            if tenant.ops_room == room:
                return tenant
        return None

    def by_slug(self, slug: str) -> Optional[TenantContext]:
        for tenant in self._active:
            if tenant.slug == slug:
                return tenant
        return None

    def allowed_repos(self) -> set[str]:
        repos = set(_FACTORY_REPOS)
        for tenant in self._active:
            repos.update(tenant.repos)
        return repos

    def _doctor_roles(self) -> None:
        roles_path = self.meta_root() / "config" / "roles.yaml"
        if not roles_path.is_file():
            logger.warning("roles.yaml missing; skip tenant App coverage check")
            return
        with roles_path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        apps = data.get("apps") or {}
        covered: set[str] = set()
        for raw in apps.values():
            if isinstance(raw, dict):
                covered.update(str(repo) for repo in (raw.get("repos") or []))
        for tenant in self._active:
            missing = sorted(name for name in tenant.repos if name not in covered)
            if missing:
                logger.warning(
                    "Tenant topology repos not on any GitHub App",
                    slug=tenant.slug,
                    repos=missing,
                )
            pm = apps.get(_PM_APP_SLUG) if isinstance(apps, dict) else None
            pm_repos = (pm or {}).get("repos") if isinstance(pm, dict) else []
            if tenant.meta_repo not in (pm_repos or []):
                logger.warning(
                    "Tenant meta repo is not on adh-dev-pm",
                    slug=tenant.slug,
                    meta_repo=tenant.meta_repo,
                )


def _load_tenants(path: Path) -> TenantsDocument:
    if not path.is_file():
        raise NotFoundError("tenants file", str(path))
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValidationError("tenants.yaml is not a mapping")
    return TenantsDocument.model_validate(data)


def _active_entries(document: TenantsDocument) -> list[TenantEntry]:
    active = [entry for entry in document.tenants if entry.active]
    if len(active) > document.max_active:
        raise ValidationError(
            f"tenants.yaml has {len(active)} active programmes; max_active is {document.max_active}"
        )
    slugs = [entry.slug for entry in active]
    if len(slugs) != len(set(slugs)):
        raise ValidationError("tenants.yaml has duplicate active slugs")
    for entry in active:
        if entry.slug == _FACTORY_SLUG:
            raise ValidationError("factory programme adh is not a product tenant")
    return active


def _load_tenant(registry: TenantRegistryService, entry: TenantEntry) -> TenantContext:
    root = registry.workspace_root() / entry.meta_repo
    if not root.is_dir():
        raise ValidationError(f"tenant checkout missing: {root}")
    programme = _read_yaml(root / "config" / "programme.yaml")
    slug = str(programme.get("programme_slug") or "").strip()
    org = str(programme.get("org") or "").strip()
    meta_repo = str(programme.get("meta_repo") or "").strip()
    if slug != entry.slug:
        raise ValidationError(
            f"programme_slug {slug!r} does not match tenants.yaml slug {entry.slug!r}"
        )
    if meta_repo != entry.meta_repo:
        raise ValidationError(
            f"programme meta_repo {meta_repo!r} does not match tenants.yaml {entry.meta_repo!r}"
        )
    expected_org = registry._settings.github_org
    if org != expected_org:
        raise ValidationError(f"programme org {org!r} does not match {expected_org!r}")
    governance = _load_governance(root, org)
    repos_raw = governance.get("repos") or {}
    if not isinstance(repos_raw, dict) or not repos_raw:
        raise ValidationError(f"{entry.slug} governance has no repos topology")
    repos = {
        str(name): str((spec or {}).get("stack") or "")
        for name, spec in repos_raw.items()
        if isinstance(spec, dict) or spec is None
    }
    raw_policy = governance.get("policy")
    policy: dict = raw_policy if isinstance(raw_policy, dict) else {}
    branch = str(policy.get("integration_branch") or "develop").strip() or "develop"
    return TenantContext(
        slug=slug,
        org=org,
        meta_repo=meta_repo,
        meta_root=str(root.resolve()),
        integration_branch=branch,
        repos=repos,
    )


def _load_governance(root: Path, org: str) -> dict:
    preferred = root / "config" / f"governance-{org}.yaml"
    if preferred.is_file():
        return _read_yaml(preferred)
    matches = sorted((root / "config").glob("governance-*.yaml"))
    if not matches:
        raise ValidationError(f"no governance-*.yaml in {root / 'config'}")
    return _read_yaml(matches[0])


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise NotFoundError("tenant yaml", str(path))
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValidationError(f"{path} is not a mapping")
    return data
