"""Global temp-paper purge matrix — event-driven, not gate-private."""

from __future__ import annotations

from src.adh_agents.collaboration.temp_papers import (
    PURGE_MATRIX,
    PurgeContext,
    PurgeEvent,
    TempFamily,
    authoring_scratch_paths,
    is_authoring_scratch,
    paths_for_family,
    resolve_purge_paths,
)


def test_promote_done_clears_authoring_and_promote_brief() -> None:
    ctx = PurgeContext(
        initiative="INIT-X",
        candidates=(
            "prd/reports/INIT-X-prd-think.md",
            "prd/reports/INIT-X-prd-think-2.md",
            "prd/reports/OTHER-prd-think.md",
            "prd/INIT-X.md",
        ),
    )
    paths = resolve_purge_paths(PurgeEvent.PROMOTE_DONE, ctx)
    assert "prd/reports/INIT-X-prd-think.md" in paths
    assert "prd/reports/INIT-X-prd-think-2.md" in paths
    assert "prd/reports/INIT-X-hermes-promote-brief.md" in paths
    assert "prd/INIT-X.md" not in paths
    assert "prd/reports/OTHER-prd-think.md" not in paths


def test_gate1_attested_is_just_one_event() -> None:
    paths = set(
        resolve_purge_paths(
            PurgeEvent.GATE1_ATTESTED,
            PurgeContext(initiative="INIT-X", meta_repo="org/meta"),
        )
    )
    assert paths == {
        "prd/reports/PE-Product-Questions-INIT-X.md",
        "prd/reports/INIT-X-hermes-gate1-brief.md",
    }
    # Read rollup survives attest — KB still needs it until enrich.
    assert not any("read-walk" in p for p in paths)


def test_prd_merged_does_not_drop_read_rollup() -> None:
    paths = resolve_purge_paths(
        PurgeEvent.PRD_MERGED,
        PurgeContext(initiative="INIT-X", meta_repo="org/meta"),
    )
    assert not any("read-walk" in p for p in paths)
    assert TempFamily.READ_ROLLUP not in PURGE_MATRIX[PurgeEvent.PRD_MERGED]


def test_kb_enrich_done_clears_rollup_and_body() -> None:
    paths = resolve_purge_paths(
        PurgeEvent.KB_ENRICH_DONE,
        PurgeContext(initiative="INIT-X", meta_repo="org/meta"),
    )
    assert "prd/reports/INIT-X-read-walk-org-meta.md" in paths
    assert "prd/reports/INIT-X-kb-enrich-pr-body.md" in paths


def test_lane_abort_covers_all_families() -> None:
    assert PURGE_MATRIX[PurgeEvent.LANE_ABORT] == frozenset(TempFamily)
    paths = resolve_purge_paths(
        PurgeEvent.LANE_ABORT,
        PurgeContext(
            initiative="INIT-X",
            meta_repo="org/meta",
            candidates=("prd/reports/INIT-X-prd-think.md",),
        ),
    )
    assert "prd/reports/INIT-X-prd-think.md" in paths
    assert "prd/reports/INIT-X-hermes-post-pm-brief.md" in paths
    assert "prd/reports/INIT-X-hermes-gate1-brief.md" in paths


def test_authoring_scratch_allowlist() -> None:
    assert is_authoring_scratch("prd/reports/INIT-X-prd-quality.md", "INIT-X")
    assert not is_authoring_scratch("prd/INIT-X.md", "INIT-X")
    assert authoring_scratch_paths(
        "INIT-X", ["prd/reports/INIT-X-prd-ask.md", "prd/INIT-X.md"]
    ) == ["prd/reports/INIT-X-prd-ask.md"]


def test_post_pm_family_path() -> None:
    assert paths_for_family(TempFamily.POST_PM_BRIEF, PurgeContext(initiative="INIT-X")) == [
        "prd/reports/INIT-X-hermes-post-pm-brief.md"
    ]
