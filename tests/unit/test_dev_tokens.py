"""Dev human reply tokens + aliases."""

from __future__ import annotations

from src.adh_agents.collaboration.human_replies import (
    ACCEPT_DEPS,
    ACCEPT_TDD_ADR,
    ANOTHER_ROUND,
    AUTHORIZE_BOARD,
    CODING_READY,
    HOLD,
    REVISE_ENGG,
    normalize_reply,
)


def test_dev_token_aliases() -> None:
    allowed = [ACCEPT_DEPS, ANOTHER_ROUND, HOLD]
    assert normalize_reply("accept engg-deps", allowed) == ACCEPT_DEPS
    assert normalize_reply("deps ok", allowed) == ACCEPT_DEPS
    assert normalize_reply("another round", allowed) == ANOTHER_ROUND

    allowed2 = [ACCEPT_TDD_ADR, CODING_READY, AUTHORIZE_BOARD, REVISE_ENGG]
    assert normalize_reply("accept adr", allowed2) == ACCEPT_TDD_ADR
    assert normalize_reply("coding-ready", allowed2) == CODING_READY
    assert normalize_reply("seed board", allowed2) == AUTHORIZE_BOARD
    assert normalize_reply("revise engineering", allowed2) == REVISE_ENGG


def test_verification_plan_coverage() -> None:
    from src.adh_agents.programmes.dev.verification_plan import (
        verification_plan_has_coverage_table,
    )

    thin = "# Verification\nno table"
    assert not verification_plan_has_coverage_table(thin)
    good = """
## Coverage table
| Layer | Proof | Owner (run) | Status |
|-------|-------|-------------|--------|
| Unit | tests/unit | CI | planned |
"""
    assert verification_plan_has_coverage_table(good)
