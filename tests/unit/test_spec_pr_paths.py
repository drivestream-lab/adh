"""Spec PR path allow-list — INIT-scoped, never full docs rglob."""

from __future__ import annotations

from src.adh_agents.programmes.dev.paths import spec_pr_body_path, spec_pr_push_paths


def test_spec_pr_push_paths_init_scoped() -> None:
    paths = spec_pr_push_paths("INIT-REALWORLD-003", "realworld-api")
    joined = "\n".join(paths)
    assert "INIT-REALWORLD-003" in joined
    assert "INIT-REALWORLD-001" not in joined
    assert "INIT-REALWORLD-002" not in joined
    assert "adr-" not in joined
    assert any(p.endswith("INIT-REALWORLD-003-realworld-api.md") for p in paths)
    assert spec_pr_body_path("INIT-REALWORLD-003", "realworld-api") in paths


def test_spec_pr_push_paths_respects_map_spec() -> None:
    paths = spec_pr_push_paths(
        "INIT-REALWORLD-003",
        "realworld-api",
        map_spec="docs/specification/product/custom-slice.md",
    )
    assert "docs/specification/product/custom-slice.md" in paths
