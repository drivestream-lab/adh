"""Verify hire spine — settings, roles, lab helpers, forge ACL (Phase 2)."""

from __future__ import annotations

from pathlib import Path

from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.programmes.verify.lab import (
    discover_lab_database_url,
    resolve_lab_paths,
)
from src.adh_agents.programmes.verify.roles import is_verify_role, verify_role
from src.adh_agents.settings import VerifyAgentSettings


def test_verify_settings_prefix_and_collab_cap() -> None:
    settings = VerifyAgentSettings(max_collab_rounds=10)
    assert settings.role_id == "adh.verify"
    assert VerifyAgentSettings.PREFIX == "ADH_VERIFY"
    assert settings.max_collab_rounds == 10
    assert settings.lab_root_name == "dev-infra-lab"
    assert settings.default_overlay_name == "realworld-local"


def test_verify_role_helpers() -> None:
    assert verify_role() == "adh.verify"
    assert is_verify_role("adh.verify")
    assert not is_verify_role("adh.coder")
    assert not is_verify_role("adh.verify.api")


def test_verify_forge_acl_no_product_commits() -> None:
    assert forge_allowed("adh.verify", "comment_pr")
    assert forge_allowed("adh.verify", "set_check")
    assert not forge_allowed("adh.verify", "open_draft_pr")
    assert not forge_allowed("adh.verify", "prd_merge")
    assert not forge_allowed("adh.verify", "land_pull_request")


def test_resolve_lab_paths_and_discover_url(tmp_path: Path) -> None:
    lab = tmp_path / "dev-infra-lab"
    overlay = tmp_path / "realworld-local"
    lab.mkdir()
    overlay.mkdir()
    (lab / ".env").write_text(
        "POSTGRES_USER=adh\nPOSTGRES_PASSWORD=secret\n",
        encoding="utf-8",
    )
    paths = resolve_lab_paths(
        tmp_path,
        lab_name="dev-infra-lab",
        overlay_name="realworld-local",
    )
    assert paths.lab_root == lab
    assert paths.overlay_root == overlay
    url = discover_lab_database_url(lab)
    assert "secret" in url
    assert "@127.0.0.1:5432/realworld" in url
