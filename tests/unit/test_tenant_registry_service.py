"""Tenant registry loads programme topology and refuses over-capacity."""

import asyncio
from pathlib import Path

import pytest

from src.configs.base_settings import BaseSettings
from src.exceptions.app_exceptions import ValidationError
from src.business_services.buzz_service import _tenant_rooms
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import RoomKind
from src.models.tenant_models import (
    knowledge_scope_key,
    memory_room_for_repo,
)


def _reset() -> None:
    BaseSettings._instances.pop("OrchestratorSettings", None)


def _write_programme(root: Path, slug: str, org: str = "drivestream-lab") -> None:
    config = root / "config"
    config.mkdir(parents=True)
    (config / "programme.yaml").write_text(
        "\n".join(
            [
                "apiVersion: launchpad/v1",
                "kind: Programme",
                f"programme_slug: {slug}",
                f"org: {org}",
                f"meta_repo: {root.name}",
                "forge:",
                "  provider: github",
            ]
        ),
        encoding="utf-8",
    )
    (config / f"governance-{org}.yaml").write_text(
        "\n".join(
            [
                f"org: {org}",
                "repos:",
                f"  {root.name}:",
                "    stack: meta-pm",
                f"  {slug}-api:",
                "    stack: python-backend",
                f"  {slug}-web:",
                "    stack: nextjs-frontend",
                f"  {slug}-local:",
                "    stack: compose-local",
                "policy:",
                "  integration_branch: develop",
            ]
        ),
        encoding="utf-8",
    )


def _workspace(tmp_path: Path, *, active_slugs: list[str]) -> Path:
    factory = tmp_path / "adh-meta" / "config"
    factory.mkdir(parents=True)
    lines = ["apiVersion: adh/v1", "kind: Tenants", "max_active: 5", "tenants:"]
    for slug in active_slugs:
        lines.extend(
            [
                f"  - slug: {slug}",
                f"    meta_repo: {slug}-meta",
                "    active: true",
            ]
        )
        _write_programme(tmp_path / f"{slug}-meta", slug)
    (factory / "tenants.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (factory / "roles.yaml").write_text(
        "\n".join(
            [
                "apps:",
                "  adh-dev-pm:",
                "    app_id: 1",
                "    pem: /tmp/pm.pem",
                "    repos: [realworld-meta]",
            ]
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_loads_realworld_topology(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace(tmp_path, active_slugs=["realworld"])
    monkeypatch.setenv("ORCH_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("ORCH_META_ROOT", str(workspace / "adh-meta"))
    monkeypatch.setenv("ORCH_GITHUB_ORG", "drivestream-lab")
    _reset()
    registry = TenantRegistryService()
    asyncio.run(registry.initialize())
    active = registry.active()
    assert len(active) == 1
    tenant = active[0]
    assert tenant.slug == "realworld"
    assert tenant.ops_room == "realworld-ops"
    assert tenant.memory_room == "realworld-meta-memory"
    assert tenant.init_prefix == "INIT-REALWORLD-"
    assert tenant.integration_branch == "develop"
    assert set(tenant.repos) == {
        "realworld-meta",
        "realworld-api",
        "realworld-web",
        "realworld-local",
    }
    assert registry.by_ops_room("realworld-ops") is tenant
    assert registry.by_ops_room("adh-ops") is None
    assert "realworld-api" in registry.allowed_repos()
    assert "adh" in registry.allowed_repos()
    _reset()


def test_sixth_active_tenant_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slugs = [f"t{i}" for i in range(6)]
    workspace = _workspace(tmp_path, active_slugs=slugs)
    monkeypatch.setenv("ORCH_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("ORCH_META_ROOT", str(workspace / "adh-meta"))
    _reset()
    registry = TenantRegistryService()
    with pytest.raises(ValidationError, match="max_active"):
        asyncio.run(registry.initialize())
    _reset()


def test_slug_mismatch_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace(tmp_path, active_slugs=["realworld"])
    programme = workspace / "realworld-meta" / "config" / "programme.yaml"
    programme.write_text(
        programme.read_text(encoding="utf-8").replace(
            "programme_slug: realworld", "programme_slug: other"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ORCH_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("ORCH_META_ROOT", str(workspace / "adh-meta"))
    _reset()
    registry = TenantRegistryService()
    with pytest.raises(ValidationError, match="programme_slug"):
        asyncio.run(registry.initialize())
    _reset()


def test_missing_checkout_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace(tmp_path, active_slugs=["realworld"])
    import shutil

    shutil.rmtree(workspace / "realworld-meta")
    monkeypatch.setenv("ORCH_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("ORCH_META_ROOT", str(workspace / "adh-meta"))
    _reset()
    registry = TenantRegistryService()
    with pytest.raises(ValidationError, match="checkout missing"):
        asyncio.run(registry.initialize())
    _reset()


def test_memory_rooms_are_global_and_per_repo() -> None:
    assert memory_room_for_repo("adh") == "adh-repo-memory"
    assert memory_room_for_repo("realworld-api") == "realworld-api-memory"
    assert memory_room_for_repo("realworld-meta") == "realworld-meta-memory"
    assert (
        knowledge_scope_key(scope="global", repo="adh", kind="pm_brief", initiative="INIT-ADH-000")
        == "global:adh:pm_brief:INIT-ADH-000"
    )
    assert (
        knowledge_scope_key(
            scope="repo",
            repo="realworld-api",
            kind="eng_grade",
            initiative="INIT-REALWORLD-HOME",
        )
        == "repo:realworld-api:eng_grade:INIT-REALWORLD-HOME"
    )


def test_buzz_seeds_repo_memory_not_programme_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path, active_slugs=["realworld"])
    monkeypatch.setenv("ORCH_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("ORCH_META_ROOT", str(workspace / "adh-meta"))
    monkeypatch.setenv("ORCH_GITHUB_ORG", "drivestream-lab")
    _reset()
    registry = TenantRegistryService()
    asyncio.run(registry.initialize())
    rooms = _tenant_rooms(registry)
    slugs = {room.slug for room in rooms}
    assert "realworld-ops" in slugs
    assert "realworld-memory" not in slugs
    assert "realworld-meta-memory" in slugs
    assert "realworld-api-memory" in slugs
    assert "realworld-web-memory" in slugs
    assert "adh-repo-memory" in slugs
    assert all(room.kind == RoomKind.MEMORY for room in rooms if room.slug.endswith("-memory"))
    _reset()
