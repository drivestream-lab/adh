"""Board seed preconditions + revise engg policy."""

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


def test_board_preconditions_block_until_accepts() -> None:
    check = board_seed_preconditions({})
    assert not check.ok
    assert "deps-acceptance" in check.reason

    slots = {
        "deps_accepted": "true",
        "tdd_adr_accepted": "true",
        "coding_ready_accepted": "true",
    }
    assert board_seed_preconditions(slots).ok


def test_board_already_seeded_blocks_without_revise() -> None:
    slots = mark_board_seeded(
        {
            "deps_accepted": "true",
            "tdd_adr_accepted": "true",
            "coding_ready_accepted": "true",
        }
    )
    assert is_post_board(slots)
    check = board_seed_preconditions(slots)
    assert not check.ok
    assert "revise engg" in check.reason


def test_revise_engg_supersedes_no_silent_rewrite() -> None:
    slots = mark_board_seeded(
        {
            "deps_accepted": "true",
            "tdd_adr_accepted": "true",
            "coding_ready_accepted": "true",
            "plan_accepted": "true",
        }
    )
    out = apply_revise_engg_slots(slots)
    assert out["board_seeded"] == "false"
    assert out.get("board_superseded")
    assert "deps_accepted" not in out
    assert out["reopen_stage"] == DEFAULT_REVISE_POLICY.reopen_stage
    assert out["revise_engg"] == "1"

    with pytest.raises(ValueError, match="silent rewrite"):
        apply_revise_engg_slots(slots, policy=ReviseEnggPolicy(allow_silent_rewrite=True))
