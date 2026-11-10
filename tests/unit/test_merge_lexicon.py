"""Post-rally merge lexicon binds go ahead and merge the product PR."""

from __future__ import annotations

from src.adh_agents.collaboration.human_replies import MERGE_PRODUCT_PR, merge_gate_tokens
from src.adh_agents.runtime.orchestrator import match_reply_token


def test_go_ahead_and_merge_phrase_both_bind() -> None:
    tokens = merge_gate_tokens()
    assert match_reply_token("go ahead", tokens) is not None
    assert match_reply_token(MERGE_PRODUCT_PR, tokens) == MERGE_PRODUCT_PR
    assert match_reply_token("authorize prd_merge", tokens) is not None
