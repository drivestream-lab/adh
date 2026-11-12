"""Dev human reply tokens + aliases."""

from __future__ import annotations

from src.adh_agents.collaboration.human_replies import (
    ACCEPT_TDD_ADR,
    ANOTHER_ROUND,
    AUTHORIZE_BOARD,
    CODING_READY,
    MERGE_SPEC_PR,
    REVISE_ENGG,
    normalize_reply,
)


def test_dev_token_aliases() -> None:
    allowed = [ACCEPT_TDD_ADR, ANOTHER_ROUND, "hold"]
    assert normalize_reply("accept adr", allowed) == ACCEPT_TDD_ADR
    assert normalize_reply("another round", allowed) == ANOTHER_ROUND

    allowed2 = [CODING_READY, MERGE_SPEC_PR, AUTHORIZE_BOARD, REVISE_ENGG]
    assert normalize_reply("coding-ready", allowed2) == CODING_READY
    assert normalize_reply("merge the spec prs", allowed2) == MERGE_SPEC_PR
    assert normalize_reply("seed board", allowed2) == AUTHORIZE_BOARD
    assert normalize_reply("revise engineering", allowed2) == REVISE_ENGG
