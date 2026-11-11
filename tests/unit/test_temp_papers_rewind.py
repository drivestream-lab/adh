"""Rewind purge matrix — start vs promote vs think vs mid-meta."""

from __future__ import annotations

from src.adh_agents.collaboration.temp_papers import (
    PURGE_MATRIX,
    PurgeContext,
    PurgeEvent,
    TempFamily,
    resolve_purge_paths,
)


def _ctx() -> PurgeContext:
    return PurgeContext(
        initiative="INIT-X",
        meta_repo="org/meta",
        candidates=(
            "prd/reports/INIT-X-prd-think.md",
            "prd/reports/INIT-X-prd-think-2.md",
            "prd/reports/INIT-X-prd-quality.md",
        ),
    )


def test_rewind_to_promote_keeps_thinks_and_prd() -> None:
    paths = resolve_purge_paths(PurgeEvent.REWIND_TO_PROMOTE, _ctx())
    assert "prd/reports/INIT-X-prd-think.md" not in paths
    assert "prd/reports/INIT-X-prd-quality.md" not in paths
    assert "prd/INIT-X.md" not in paths
    assert "prd/reports/INIT-X-hermes-promote-brief.md" in paths
    assert "prd/reports/INIT-X-hermes-post-pm-brief.md" in paths
    assert TempFamily.AUTHORING_SCRATCH not in PURGE_MATRIX[PurgeEvent.REWIND_TO_PROMOTE]
    assert TempFamily.PROMOTED_PRD not in PURGE_MATRIX[PurgeEvent.REWIND_TO_PROMOTE]


def test_rewind_to_think_keeps_thinks_purges_prd() -> None:
    paths = resolve_purge_paths(PurgeEvent.REWIND_TO_THINK, _ctx())
    assert "prd/reports/INIT-X-prd-think.md" not in paths
    assert "prd/reports/INIT-X-prd-quality.md" in paths
    assert "prd/INIT-X.md" in paths
    assert "prd/reports/INIT-X-hermes-promote-brief.md" in paths


def test_rewind_start_purges_all_thinks_and_prd() -> None:
    paths = resolve_purge_paths(PurgeEvent.REWIND_START, _ctx())
    assert "prd/reports/INIT-X-prd-think.md" in paths
    assert "prd/reports/INIT-X-prd-think-2.md" in paths
    assert "prd/reports/INIT-X-prd-quality.md" in paths
    assert "prd/INIT-X.md" in paths
    assert PURGE_MATRIX[PurgeEvent.REWIND_START] == frozenset(TempFamily)


def test_rewind_gate_reopen_purges_nothing() -> None:
    assert PURGE_MATRIX[PurgeEvent.REWIND_GATE_REOPEN] == frozenset()
    assert resolve_purge_paths(PurgeEvent.REWIND_GATE_REOPEN, _ctx()) == []


def test_rewind_to_acceptance_keeps_resolution() -> None:
    paths = set(resolve_purge_paths(PurgeEvent.REWIND_TO_ACCEPTANCE, _ctx()))
    assert "prd/reports/INIT-X-hermes-post-pm-brief.md" in paths
    assert "prd/reports/Impact-Map-INIT-X.md" in paths
    assert "prd/reports/Resolution-INIT-X.md" not in paths
    assert "prd/reports/Validation-Report-INIT-X.md" not in paths
