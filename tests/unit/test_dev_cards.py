"""Hermes multi-thought Dev card parser."""

from __future__ import annotations

from src.adh_agents.programmes.dev.cards import card_bluf, parse_dev_thought_card


def test_parse_dev_thought_card() -> None:
    body = """
## ADR why
Prefer Postgres for durable tasks.

## API why
Keep Buzz REST thin.

## Deps
adh before realworld-api.

## Verification gaps
No live verify for board seed yet.
"""
    card = parse_dev_thought_card(body)
    assert card is not None
    assert "Postgres" in card.adr_why
    assert "Buzz" in card.api_why
    assert "adh" in card.deps
    assert "live verify" in card.verification_gaps
    assert "ADR:" in card_bluf(card)


def test_parse_empty() -> None:
    assert parse_dev_thought_card("") is None
    assert parse_dev_thought_card("no sections here") is None
