"""Local meta sync after durable land — never silent dirty drift."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.exceptions.app_exceptions import ValidationError
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.models.tenant_models import TenantContext


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _git_user(cwd: Path) -> None:
    _git(cwd, "config", "user.email", "test@example.com")
    _git(cwd, "config", "user.name", "Test")


def _svc() -> PmWorkspaceService:
    svc = object.__new__(PmWorkspaceService)
    return svc  # type: ignore[return-value]


@pytest.fixture()
def meta_repo(tmp_path: Path) -> tuple[Path, Path, TenantContext]:
    """Bare origin + local clone on develop."""
    origin = tmp_path / "origin.git"
    local = tmp_path / "meta"
    _git(tmp_path, "init", "--bare", str(origin))
    _git(tmp_path, "clone", str(origin), str(local))
    _git_user(local)
    _git(local, "checkout", "-b", "develop")
    (local / "README.md").write_text("hi\n", encoding="utf-8")
    _git(local, "add", "README.md")
    _git(local, "commit", "-m", "init")
    _git(local, "push", "-u", "origin", "develop")
    tenant = TenantContext(
        slug="demo",
        org="org",
        meta_repo="demo-meta",
        meta_root=str(local),
        ops_room="demo-ops",
        integration_branch="develop",
        init_prefix="INIT-",
    )
    return origin, local, tenant


def test_sync_ff_clean(meta_repo: tuple[Path, Path, TenantContext]) -> None:
    origin, local, tenant = meta_repo
    # Advance origin tip.
    other = local.parent / "other"
    _git(local.parent, "clone", str(origin), str(other))
    _git_user(other)
    _git(other, "checkout", "develop")
    (other / "README.md").write_text("hi\nmore\n", encoding="utf-8")
    _git(other, "add", "README.md")
    _git(other, "commit", "-m", "advance")
    _git(other, "push", "origin", "develop")

    result = _svc().sync_integration_branch(tenant)
    assert result["branch"] == "develop"
    assert result["sha"]
    assert result["mode"] in {"ff_only", "hard_reset_diverged"}
    assert (local / "README.md").read_text(encoding="utf-8") == "hi\nmore\n"


def test_sync_dirty_stalls(meta_repo: tuple[Path, Path, TenantContext]) -> None:
    _origin, local, tenant = meta_repo
    (local / "dirty.txt").write_text("nope\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="dirty"):
        _svc().sync_integration_branch(tenant)


def test_sync_dirty_force(meta_repo: tuple[Path, Path, TenantContext]) -> None:
    _origin, local, tenant = meta_repo
    (local / "dirty.txt").write_text("nope\n", encoding="utf-8")
    result = _svc().sync_integration_branch(tenant, force=True)
    assert result["mode"] == "hard_reset"
    assert not (local / "dirty.txt").exists()
