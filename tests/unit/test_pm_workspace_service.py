"""PM workspace writes think files locally and commits on develop as adh-dev-pm."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.configs.base_settings import BaseSettings
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.pm_workspace_service import (
    PmWorkspaceService,
    next_free_think_runs,
    next_programme_init,
    skeleton_material_fails,
)
from src.models.tenant_models import TenantContext


def _reset_settings() -> None:
    BaseSettings._instances.pop("HermesSettings", None)
    BaseSettings._instances.pop("OrchestratorSettings", None)


def _tenant(meta_root: Path) -> TenantContext:
    return TenantContext(
        slug="realworld",
        org="drivestream-lab",
        meta_repo="realworld-meta",
        meta_root=str(meta_root),
        integration_branch="develop",
        repos={"realworld-meta": "meta-pm"},
    )


def _roles_yaml() -> str:
    return "\n".join(
        [
            "apps:",
            "  adh-dev-pm:",
            "    app_id: 5508966",
            "    installation_id: 1",
            "    pem: /tmp/pm.pem",
            "    repos: [realworld-meta]",
            "    used_by: hermes-pm",
        ]
    )


def test_publish_writes_reports_locally(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = tmp_path / "realworld-meta"
    meta.mkdir()
    monkeypatch.setenv("ORCH_META_ROOT", str(tmp_path / "no-meta"))
    monkeypatch.setenv("ORCH_WORKSPACE_ROOT", str(tmp_path))
    _reset_settings()
    github = MagicMock()
    github.initialize = AsyncMock()
    service = PmWorkspaceService(github)
    tenant = _tenant(meta)
    result = asyncio.run(
        service.publish(
            tenant, "prd/reports/INIT-X-prd-think.md", "# think C1\n", "docs(INIT-X): C1"
        )
    )
    dest = meta / "prd" / "reports" / "INIT-X-prd-think.md"
    assert dest.is_file()
    assert dest.read_text(encoding="utf-8") == "# think C1\n"
    assert result["local_path"] == str(dest)
    github.installation_token.assert_not_called()
    _reset_settings()


def test_publish_commits_on_develop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = tmp_path / "realworld-meta"
    meta.mkdir()
    roles = tmp_path / "adh-meta" / "config"
    roles.mkdir(parents=True)
    (roles / "roles.yaml").write_text(_roles_yaml(), encoding="utf-8")
    monkeypatch.setenv("ORCH_META_ROOT", str(tmp_path / "adh-meta"))
    _reset_settings()
    github = MagicMock()
    github.initialize = AsyncMock()
    github.installation_token = AsyncMock(return_value=("tok", {"contents": "write"}))
    github.put_text_file = AsyncMock(
        return_value={
            "sha": "deadbeef",
            "commit_sha": "cafebabe",
            "path": "prd/reports/INIT-X-prd-think.md",
            "branch": "develop",
        }
    )
    service = PmWorkspaceService(github)
    result = asyncio.run(
        service.publish(
            _tenant(meta),
            "prd/reports/INIT-X-prd-think.md",
            "# think C1\n",
            "docs(INIT-X): C1",
        )
    )
    github.installation_token.assert_awaited()
    kwargs = github.put_text_file.await_args.kwargs
    assert kwargs["branch"] == "develop"
    assert kwargs["path"] == "prd/reports/INIT-X-prd-think.md"
    assert result["github"]["commit_sha"] == "cafebabe"
    _reset_settings()


def test_publish_refuses_meta_not_on_pm_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = tmp_path / "other-meta"
    meta.mkdir()
    roles = tmp_path / "adh-meta" / "config"
    roles.mkdir(parents=True)
    (roles / "roles.yaml").write_text(_roles_yaml(), encoding="utf-8")
    monkeypatch.setenv("ORCH_META_ROOT", str(tmp_path / "adh-meta"))
    _reset_settings()
    github = MagicMock()
    github.initialize = AsyncMock()
    service = PmWorkspaceService(github)
    tenant = TenantContext(
        slug="other",
        org="drivestream-lab",
        meta_repo="other-meta",
        meta_root=str(meta),
        integration_branch="develop",
        repos={"other-meta": "meta-pm"},
    )
    with pytest.raises(ValidationError, match="not on identity adh-dev-pm"):
        asyncio.run(service.publish(tenant, "prd/reports/x.md", "# x\n", "docs"))
    github.put_text_file.assert_not_called()
    _reset_settings()


def test_inventory_reads_init_ids_from_meta(tmp_path: Path) -> None:
    meta = tmp_path / "realworld-meta"
    reports = meta / "prd" / "reports"
    reports.mkdir(parents=True)
    (meta / "prd" / "README.md").write_text("# PRDs\n", encoding="utf-8")
    (meta / "prd" / "INIT-REALWORLD-HOME.md").write_text("# prd\n", encoding="utf-8")
    (reports / "INIT-REALWORLD-HOME-prd-think.md").write_text("# c1\n", encoding="utf-8")
    (reports / "INIT-REALWORLD-HOME-prd-ask.md").write_text("# ask\n", encoding="utf-8")
    (reports / "INIT-REALWORLD-HOME-prd-recommend.md").write_text("# rec\n", encoding="utf-8")
    (reports / "INIT-REALWORLD-PENDING-prd-think.md").write_text("# skip\n", encoding="utf-8")
    service = PmWorkspaceService(MagicMock())
    listing = service.inventory(_tenant(meta))
    assert listing.inits == ["INIT-REALWORLD-HOME"]
    assert listing.think_paths == ["prd/reports/INIT-REALWORLD-HOME-prd-think.md"]
    assert listing.prd_paths == ["prd/INIT-REALWORLD-HOME.md"]


def test_next_free_think_skips_existing() -> None:
    existing = ["prd/reports/INIT-X-prd-think.md", "prd/reports/INIT-X-prd-think-2.md"]
    assert next_free_think_runs("INIT-X", existing) == (3, 4)


def test_next_programme_init_uses_harness_numbering() -> None:
    prefix = "INIT-REALWORLD-"
    assert next_programme_init(prefix, []) == "INIT-REALWORLD-001"
    assert next_programme_init(prefix, ["INIT-REALWORLD-001"]) == "INIT-REALWORLD-002"
    assert next_programme_init(prefix, ["INIT-REALWORLD-017"]) == "INIT-REALWORLD-018"
    assert next_programme_init(prefix, ["INIT-REALWORLD-HOME-PUBLISH-001"]) == "INIT-REALWORLD-001"


def test_skeleton_material_fails_empty_job_and_placeholders() -> None:
    fails = skeleton_material_fails(
        "- **Job:** (none)\n- CAP-01:  (J: J-01)\n→ n/a\nJ-01: Visitor / ? → ?\n"
    )
    assert "B1 Job is empty" in fails
    assert "B2 CAP text is empty" in fails
    assert "B3 Observable result is n/a" in fails
    assert "B14 Journeys are placeholders" in fails
    assert skeleton_material_fails("- **Job:** Empty home is a product state.\n") == []
    assert (
        skeleton_material_fails(
            "## Job Statement\n\n**Job to be Done:**\nVisitor sees empty home.\n"
        )
        == []
    )
