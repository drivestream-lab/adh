"""Helpful-army coach + delivery lexicon guards."""

from __future__ import annotations

from src.adh_agents.collaboration.delivery_voice import (
    delivery_phrase,
    forbidden_buzz_hits,
)
from src.adh_agents.collaboration.gate_coach import (
    TokenAction,
    format_human_next,
    tokens_from_reply,
)
from src.adh_agents.programmes.pe.gate1_brief import format_gate1_buzz_bluf


def test_delivery_phrase_maps_hops() -> None:
    assert delivery_phrase("prd-merge") == "product merge into develop"
    assert delivery_phrase("kb-enrich") == "knowledge docs PR"
    assert delivery_phrase("product_brief") == "product brief"


def test_format_human_next_skeleton() -> None:
    body = format_human_next(
        i_did="Opened the product draft PR.",
        recommend="go ahead",
        recommend_why="Land when satisfied.",
        evidence="PR: https://example/pull/3",
        outside_adh="Skim the PR in Cursor. Do not merge on GitHub yourself.",
        tokens=[
            TokenAction("go ahead", "undraft + merge + sync local develop"),
            TokenAction("hold", "park — nothing lands"),
        ],
    )
    assert "**I did.**" in body
    assert "**Recommend.** `go ahead`" in body
    assert "**Evidence.**" in body
    assert "**Before you post.**" in body
    assert "`go ahead` → I will undraft + merge + sync local develop" in body
    assert forbidden_buzz_hits(body) == []


def test_forbid_jargon_and_forge_click() -> None:
    dirty = "Gate‑1 ready. Next: merge on forge. See pe.review / kb.enrich."
    hits = forbidden_buzz_hits(dirty)
    assert "gate‑1" in hits or "gate-1" in hits
    assert "merge on forge" in hits
    assert any("kb.enrich" in h or "pe.review" in h for h in hits)


def test_gate1_buzz_is_delivery_voice() -> None:
    bluf = format_gate1_buzz_bluf(
        initiative="INIT-X",
        round_number=1,
        max_rounds=4,
        question_count=3,
        brief_path="prd/reports/INIT-X-hermes-gate1-brief.md",
        questions_path="prd/reports/PE-Product-Questions-INIT-X.md",
    )
    assert "**I did.**" in bluf
    assert "product questions" in bluf.lower() or "product brief" in bluf.lower()
    assert "**Buying.**" not in bluf
    assert "ack_pe" not in bluf
    assert "park" in bluf or "another round" in bluf
    assert forbidden_buzz_hits(bluf) == []


def test_tokens_from_reply() -> None:
    toks = tokens_from_reply(
        ["go ahead", "hold"],
        wills={"go ahead": "land the PR", "hold": "park"},
    )
    assert toks[0].token == "go ahead"
    assert toks[0].agent_will == "land the PR"
