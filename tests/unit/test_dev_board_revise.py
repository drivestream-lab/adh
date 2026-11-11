"""Board seed YAML predicates + revise engg policy."""

from __future__ import annotations

import pytest

from src.adh_agents.programmes.dev.board_seed import (
    board_seed_preconditions,
    mark_board_seeded,
)
from src.adh_agents.programmes.dev.revise import (
    DEFAULT_REVISE_POLICY,
    ReviseEnggPolicy,
    apply_revise_engg_slots,
    is_post_board,
)


def test_board_preconditions_yaml_predicates() -> None:
    check = board_seed_preconditions({})
    assert not check.ok
    assert "spec-pr-merged" in check.reason
    assert "deps-acceptance" not in check.reason

    slots = {
        "spec_pr_merged": "true",
        "tdd_adr_accepted": "true",
        "coding_ready_accepted": "true",
        "implementation_plan_current": "true",
        "workmanifest_contract_pass": "true",
    }
    assert board_seed_preconditions(slots).ok


def test_board_already_seeded_blocks_without_revise() -> None:
    slots = mark_board_seeded(
        {
            "spec_pr_merged": "true",
            "tdd_adr_accepted": "true",
            "coding_ready_accepted": "true",
            "implementation_plan_current": "true",
            "workmanifest_contract_pass": "true",
        }
    )
    assert is_post_board(slots)
    check = board_seed_preconditions(slots)
    assert not check.ok
    assert "revise engg" in check.reason


def test_revise_engg_reopens_spec_draft() -> None:
    slots = mark_board_seeded(
        {
            "spec_pr_merged": "true",
            "tdd_adr_accepted": "true",
            "coding_ready_accepted": "true",
            "implementation_plan_current": "true",
            "workmanifest_contract_pass": "true",
        }
    )
    out = apply_revise_engg_slots(slots)
    assert out["board_seeded"] == "false"
    assert out.get("board_superseded")
    assert "tdd_adr_accepted" not in out
    assert out["reopen_stage"] == "spec-draft"
    assert out["reopen_stage"] == DEFAULT_REVISE_POLICY.reopen_stage
    assert out["revise_engg"] == "1"

    with pytest.raises(ValueError, match="silent rewrite"):
        apply_revise_engg_slots(slots, policy=ReviseEnggPolicy(allow_silent_rewrite=True))
