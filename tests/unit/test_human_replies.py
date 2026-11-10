"""Human reply lexicon + aliases."""

from __future__ import annotations

from src.adh_agents.collaboration.human_replies import (
    MERGE_PRODUCT_PR,
    PARK,
    merge_gate_tokens,
    normalize_reply,
    strip_legacy_ack,
    tokens_equivalent,
)
from src.adh_agents.runtime.orchestrator import match_reply_token


def test_merge_aliases() -> None:
    allowed = merge_gate_tokens()
    assert normalize_reply("go ahead", allowed) in allowed
    assert normalize_reply("merge the product PR", allowed) == MERGE_PRODUCT_PR
    assert normalize_reply("park", allowed) == PARK
    assert normalize_reply("hold", allowed) == PARK


def test_match_reply_token_uses_aliases() -> None:
    tokens = merge_gate_tokens()
    assert match_reply_token("go ahead", tokens) is not None
    assert match_reply_token("merge the product PR", tokens) == MERGE_PRODUCT_PR
    assert tokens_equivalent("go ahead", MERGE_PRODUCT_PR)


def test_strip_legacy_ack() -> None:
    assert "ack_pe" not in strip_legacy_ack(["ack_pe", "go ahead"])
