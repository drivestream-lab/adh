"""Shared Hermes decision-card parser — product promote + post-PM delta."""

from __future__ import annotations

from src.business_services.hermes.collaboration.brief_service import HermesBriefService
from src.business_services.hermes.decision_card import (
    CARD_POSTPM,
    CARD_PROMOTE,
    parse_bullets,
    parse_postpm_decision_card,
    parse_promote_decision_card,
)

_PROMOTE = """
# Hermes promote brief — INIT-RW-001

recommend: C2

## bluf
Promote C2 — strangers must find published articles on home, or this INIT fails.

## locking
- Home lists published articles for anonymous visitors
- Read shows title, body, and author name outside the write session
- Two authors' articles both stay listed

## not_locking
- Required short description at publish
- Newest-first ranking as a product rule

## revise_if
- Need description-at-publish as the bar → pick C1 instead

## example
Maya publishes; Sam (logged out) finds it on home and reads body + by Maya.

## options
- C1 — thinner seam
- C2 — public catalog on home
"""

_POSTPM = """
# Hermes post-PM brief — INIT-RW-001

recommend: confirm

## bluf
Proceed — Criticals cleared; deferred items do not undercut stranger-on-home done.

## changed
- Header/metadata cleaned so the promoted PRD reads as the live SSOT
- Empty-home vs outage wording tightened on the reader path

## deferred
- Exact identity import field list — product risk: attribution may be thin until named

## still_risky
- none

## example
A stranger saw empty home earlier; after publish they reopen home and read title, body, author name.

## options
- confirm — proceed; Hermes runs impact-map next
- revise — hold and edit the PRD first
"""


def test_parse_promote_decision_card() -> None:
    card = parse_promote_decision_card(_PROMOTE, allowed_labels=["C1", "C2"])
    assert card is not None
    assert card.recommend == "C2"
    assert card.card_kind == CARD_PROMOTE
    assert "strangers" in card.bluf
    assert len(card.locking) == 3
    assert "description" in card.not_locking[0].lower()
    assert "Maya" in card.example


def test_parse_promote_rejects_legacy_why_only() -> None:
    legacy = """
recommend: C2
## recommend_why
old why
## example
old example
"""
    assert parse_promote_decision_card(legacy, allowed_labels=["C2"]) is None


def test_parse_postpm_delta_card() -> None:
    card = parse_postpm_decision_card(_POSTPM)
    assert card is not None
    assert card.recommend == "confirm"
    assert card.card_kind == CARD_POSTPM
    assert card.changed and "SSOT" in card.changed[0]
    assert card.deferred and "identity" in card.deferred[0].lower()
    assert card.still_risky == ("none",)


def test_parse_postpm_rejects_promote_shaped_locking_only() -> None:
    legacy = """
recommend: confirm
## bluf
Confirm the job.
## locking
- Restate the PRD
## not_locking
- none
## revise_if
- none
## example
Someone publishes.
"""
    assert parse_postpm_decision_card(legacy) is None


def test_parse_bullets_caps_at_three() -> None:
    body = "\n".join(f"- item {i}" for i in range(1, 6))
    assert parse_bullets(body) == ("item 1", "item 2", "item 3")


def test_format_brief_markdown_promote_labels() -> None:
    svc = HermesBriefService()
    brief = svc.build_brief(
        purpose="authoring-promote",
        node_id="authoring-promote",
        question="Which product bet?",
        recommend="C2",
        bluf="Promote C2 — public catalog on home.",
        card_kind=CARD_PROMOTE,
        locking=["Home lists for strangers"],
        not_locking=["Description-at-publish"],
        revise_if=["Need subtitle tax → C1"],
        example="Maya publishes; Sam finds it.",
        options=["C2 — copy think-2"],
        reply_tokens=["C2", "skip"],
    )
    md = svc.format_brief_markdown(brief)
    assert "**Recommendation.** `C2`" in md
    assert "**Buying.**" in md
    assert "**Not buying.**" in md
    assert "**Choose another if.**" in md
    assert "**BLUF.**" not in md


def test_format_brief_markdown_postpm_delta_labels() -> None:
    svc = HermesBriefService()
    brief = svc.build_brief(
        purpose="prd-impact-acceptance",
        node_id="prd-impact-acceptance",
        question="Proceed or hold?",
        recommend="confirm",
        bluf="Proceed — Criticals cleared.",
        card_kind=CARD_POSTPM,
        locking=["Metadata cleaned"],
        not_locking=["Identity field list deferred"],
        revise_if=["none"],
        example="Stranger finds the article on home.",
        options=["confirm — proceed"],
        reply_tokens=["confirm", "revise"],
    )
    md = svc.format_brief_markdown(brief)
    assert "**What changed.**" in md
    assert "**Deferred.**" in md
    assert "**Still risky.**" in md
    assert "**Buying.**" not in md
