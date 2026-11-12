"""Board seed YAML predicates + revise engg / reseed board policy."""

from __future__ import annotations

import pytest

from src.adh_agents.programmes.dev.board_seed import (
    apply_reseed_board_slots,
    board_seed_preconditions,
    mark_board_seeded,
)
from src.adh_agents.programmes.dev.revise import (
    DEFAULT_REVISE_POLICY,
    ReviseEnggPolicy,
    apply_revise_engg_slots,
    is_post_board,
)


def _ready_slots() -> dict[str, str]:
    return {
        "spec_pr_merged": "true",
        "tdd_adr_accepted": "true",
        "coding_ready_accepted": "true",
        "implementation_plan_current": "true",
        "workmanifest_contract_pass": "true",
    }


def test_board_preconditions_yaml_predicates() -> None:
    check = board_seed_preconditions({})
    assert not check.ok
    assert "spec-pr-merged" in check.reason
    assert "deps-acceptance" not in check.reason

    assert board_seed_preconditions(_ready_slots()).ok


def test_board_already_seeded_blocks_without_revise_or_reseed() -> None:
    slots = mark_board_seeded(_ready_slots())
    assert is_post_board(slots)
    check = board_seed_preconditions(slots)
    assert not check.ok
    assert "reseed board" in check.reason
    assert "revise engg" in check.reason


def test_reseed_board_allows_authorize_again() -> None:
    slots = mark_board_seeded(_ready_slots())
    out = apply_reseed_board_slots(slots)
    assert out["board_seeded"] == "false"
    assert out.get("board_superseded")
    assert out.get("reseed_board") == "1"
    assert out.get("spec_pr_merged") == "true"
    assert out.get("workmanifest_contract_pass") == "true"
    assert out.get("tdd_adr_accepted") == "true"
    assert "board_authorized" not in out
    assert board_seed_preconditions(out).ok


def test_mark_board_seeded_clears_reseed_flag() -> None:
    slots = apply_reseed_board_slots(mark_board_seeded(_ready_slots()))
    assert slots.get("reseed_board") == "1"
    done = mark_board_seeded(slots, marker="create-board-tickets:INIT-X")
    assert done["board_seeded"] == "true"
    assert "reseed_board" not in done


def test_revise_engg_reopens_spec_draft() -> None:
    slots = mark_board_seeded(_ready_slots())
    out = apply_revise_engg_slots(slots)
    assert out["board_seeded"] == "false"
    assert out.get("board_superseded")
    assert "tdd_adr_accepted" not in out
    assert out["reopen_stage"] == "spec-draft"
    assert out["reopen_stage"] == DEFAULT_REVISE_POLICY.reopen_stage
    assert out["revise_engg"] == "1"

    with pytest.raises(ValueError, match="silent rewrite"):
        apply_revise_engg_slots(slots, policy=ReviseEnggPolicy(allow_silent_rewrite=True))
