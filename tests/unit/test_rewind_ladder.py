"""Pure rewind ladder — can / cannot / outside."""

from __future__ import annotations

from src.adh_agents.collaboration.temp_papers import PurgeEvent
from src.adh_agents.runtime.rewind import (
    RewindTargetId,
    RewindTipFacts,
    build_ladder,
    format_ladder_body,
)


def test_pre_promote_ladder_includes_start_and_think() -> None:
    ladder = build_ladder(
        RewindTipFacts(
            stage="authoring-promote",
            brief_purpose="authoring-promote",
            has_open_gate=True,
        )
    )
    assert not ladder.denied
    ids = [t.id for t in ladder.can]
    assert RewindTargetId.GATE_REOPEN in ids
    assert RewindTargetId.AUTHORING_PROMOTE in ids
    assert RewindTargetId.AUTHORING_THINK in ids
    assert RewindTargetId.START in ids
    assert RewindTargetId.PRD_PR_ACTION not in ids
    promote = next(t for t in ladder.can if t.id is RewindTargetId.AUTHORING_PROMOTE)
    assert promote.purge_event is PurgeEvent.REWIND_TO_PROMOTE
    assert promote.close_prs is False


def test_draft_pr_sets_close_flag() -> None:
    ladder = build_ladder(
        RewindTipFacts(
            stage="prd-pr-action",
            brief_purpose="prd-pr-action",
            has_open_gate=True,
            has_open_draft_pr=True,
        )
    )
    start = next(t for t in ladder.can if t.id is RewindTargetId.START)
    assert start.close_prs is True
    reopen = next(t for t in ladder.can if t.id is RewindTargetId.GATE_REOPEN)
    assert reopen.close_prs is False


def test_post_merge_empty_can() -> None:
    ladder = build_ladder(
        RewindTipFacts(
            stage="prd-merge",
            merge_sha="abc123",
            product_landed=True,
            has_open_gate=False,
        )
    )
    assert ladder.denied
    assert ladder.deny_reason == "post_product_merge"
    assert ladder.can == ()
    body = format_ladder_body(ladder)
    assert "Cannot rewind" in body
    assert "Outside ADH" in body
    assert "Can rewind" in body


def test_god_deny() -> None:
    ladder = build_ladder(
        RewindTipFacts(
            stage="authoring-promote",
            brief_purpose="authoring-promote",
            has_open_gate=True,
            is_god=True,
        )
    )
    assert ladder.denied
    assert ladder.deny_reason == "god_mode"
    assert ladder.can == ()


def test_target_by_index() -> None:
    ladder = build_ladder(
        RewindTipFacts(
            stage="authoring-promote",
            brief_purpose="authoring-promote",
            has_open_gate=True,
        )
    )
    assert ladder.target_by_index(0) is None
    first = ladder.target_by_index(1)
    assert first is not None
    assert first.id is RewindTargetId.GATE_REOPEN
    assert ladder.target_by_index(99) is None
