"""Stratum-shaped Hermes dry-run — L1 pack render + L2 delivery parse (CI).

No tenant onboard, Buzz, or forge. Fixtures under tests/fixtures/hermes/stratum/.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from src.adh_agents.programmes.dev.impact_repos import parse_affected_repos
from src.adh_agents.programmes.dev.paths import (
    spec_pr_branch,
    spec_pr_push_paths,
    spec_slice_path,
)
from src.infra_services.prompt_service import PromptService
from tests._helpers.hermes_stratum import (
    FIXTURE_ROOT,
    load_index,
    pack_variables,
    read_fixture,
)


@pytest.fixture(scope="module")
def stratum_index():
    return load_index()


@pytest.fixture(scope="module")
def prompts():
    service = PromptService(MagicMock())
    asyncio.run(service.initialize())
    yield service
    asyncio.run(service.close())


def test_stratum_fixture_bank_present(stratum_index) -> None:
    assert FIXTURE_ROOT.is_dir()
    scenarios = stratum_index["scenarios"]
    assert set(scenarios) >= {"edge-008", "core-002", "hitl-001", "iac-004"}
    for sid, sc in scenarios.items():
        d = FIXTURE_ROOT / sc["dir"]
        assert (d / sc["impact_map"]).is_file(), sid
        assert (d / sc["think"]).is_file(), sid
        assert (d / sc["quality"]).is_file(), sid


@pytest.mark.parametrize(
    "scenario_id",
    ["edge-008", "core-002", "hitl-001", "iac-004"],
)
def test_l1_all_hops_render(prompts, stratum_index, scenario_id: str) -> None:
    """Every hop renders with Stratum vars; initiative appears in output."""
    sc = stratum_index["scenarios"][scenario_id]
    initiative = sc["initiative"]
    for hop in stratum_index["hops"]:
        vars_ = pack_variables(scenario_id, hop["id"])
        if hop["kind"] == "copy":
            body = prompts.render_copy(hop["pack"], vars_)
            assert initiative in body, hop["id"]
            assert body.strip(), hop["id"]
        else:
            rendered = prompts.render(hop["pack"], vars_)
            blob = f"{rendered.system}\n{rendered.user}"
            assert initiative in blob, hop["id"]
            assert "{{" not in blob, f"unresolved placeholder in {hop['id']}"


@pytest.mark.parametrize(
    "scenario_id",
    ["edge-008", "core-002", "hitl-001", "iac-004"],
)
def test_l2_affected_only_parse(stratum_index, scenario_id: str) -> None:
    """Multi-table Stratum Impact-Maps → Affected only (Deferred never Spec'd)."""
    sc = stratum_index["scenarios"][scenario_id]
    meta = stratum_index["meta_repo"]
    body = read_fixture(scenario_id, sc["impact_map"])
    got = parse_affected_repos(body, meta_repo=meta)
    got_repos = [r.repo for r in got]
    expected = [row["repo"] for row in sc["expected_affected"]]
    assert got_repos == expected

    for row, impact in zip(sc["expected_affected"], got, strict=True):
        assert impact.full_name == row["full_name"]
        assert impact.spec_to_create == row["spec_to_create"]

    forbidden = set(sc.get("deferred_must_not_include") or [])
    assert forbidden.isdisjoint(got_repos)

    # Deferred / transitive tables still mention forbidden names in the file —
    # parser must ignore those rows even though the strings exist.
    for name in forbidden:
        if name == meta:
            continue
        # Only assert presence-in-file when the map actually lists them.
        if name in body and name not in expected:
            assert name not in got_repos


@pytest.mark.parametrize(
    "scenario_id",
    ["edge-008", "core-002", "hitl-001", "iac-004"],
)
def test_l2_spec_paths_and_branch(stratum_index, scenario_id: str) -> None:
    sc = stratum_index["scenarios"][scenario_id]
    initiative = sc["initiative"]
    branch = spec_pr_branch(initiative)
    assert branch.startswith("chore/spec-")
    assert "docs/" not in branch

    for row in sc["expected_affected"]:
        slice_path = spec_slice_path(initiative, row["repo"], map_spec=row["spec_to_create"])
        assert row["spec_to_create"].split("/")[-1] in slice_path or slice_path.endswith(
            row["spec_to_create"]
        )
        paths = spec_pr_push_paths(initiative, row["repo"], map_spec=row["spec_to_create"])
        assert slice_path in paths
        # INIT-scoped only — no whole-tree rglob stand-in.
        for p in paths:
            assert initiative.lower() in p.lower() or initiative in p


def test_l2_edge_008_does_not_spec_deferred_platform_or_iac(stratum_index) -> None:
    """Pressure case that RealWorld missed: Deferred platform-core + iac."""
    sc = stratum_index["scenarios"]["edge-008"]
    body = read_fixture("edge-008", sc["impact_map"])
    assert "stratum-platform-core" in body
    assert "stratum-iac-infra" in body
    got = parse_affected_repos(body, meta_repo=stratum_index["meta_repo"])
    assert [r.repo for r in got] == ["stratum-edge-agent"]
