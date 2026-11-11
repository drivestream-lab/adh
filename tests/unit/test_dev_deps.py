"""Engg-Deps artefact helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.adh_agents.programmes.dev.deps import (
    deps_has_visible_dag,
    ensure_engg_deps_stub,
    parse_deps_tiers,
)
from src.adh_agents.programmes.dev.paths import engg_deps_path


def test_engg_deps_path() -> None:
    assert engg_deps_path("init-007") == "prd/reports/Engg-Deps-INIT-007.md"


def test_parse_deps_tiers() -> None:
    body = """
# Engg-Deps
## Tier 0 — foundations
- `adh` — core
- `realworld-api` — api
## Tier 1 — dependents
- `realworld-web` — ui
"""
    tiers = parse_deps_tiers(body)
    assert tiers[0] == (0, ["adh", "realworld-api"])
    assert tiers[1] == (1, ["realworld-web"])
    assert deps_has_visible_dag(body)


def test_deps_empty_not_visible() -> None:
    assert not deps_has_visible_dag("# Engg-Deps\n## Tier 0\n- `(none)`\n")


def test_ensure_stub_writes_once() -> None:
    ws = MagicMock()
    ws.read_local.return_value = ""
    tenant = MagicMock()
    path = ensure_engg_deps_stub(
        ws,
        tenant,
        initiative="INIT-007",
        impact_map_body="repo: drivestream-lab/adh\n`org/other`",
    )
    assert path.endswith("Engg-Deps-INIT-007.md")
    ws.write_local.assert_called_once()
    written = ws.write_local.call_args.args[2]
    assert "Tier 0" in written
    assert "adh" in written or "drivestream-lab/adh" in written

    ws.read_local.return_value = written
    ensure_engg_deps_stub(ws, tenant, initiative="INIT-007", impact_map_body="ignored")
    assert ws.write_local.call_count == 1
