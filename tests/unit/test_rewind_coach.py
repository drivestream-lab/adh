"""Rewind coach helpers — pick parse + ladder serialization."""

from __future__ import annotations

from src.adh_agents.programmes.pm.rewind_coach import RewindCoachProgramme
from src.adh_agents.runtime.rewind import RewindTipFacts, build_ladder, format_ladder_body


def test_parse_pick_with_reason_line() -> None:
    parsed = RewindCoachProgramme._parse_pick("rewind 2\nreason: wrong C-pick")
    assert parsed == (2, "wrong C-pick")


def test_parse_pick_inline_reason() -> None:
    parsed = RewindCoachProgramme._parse_pick("rewind 1 reason: try again")
    assert parsed is not None
    assert parsed[0] == 1
    assert "try again" in parsed[1]


def test_ladder_roundtrip() -> None:
    ladder = build_ladder(
        RewindTipFacts(
            stage="authoring-promote",
            brief_purpose="authoring-promote",
            has_open_gate=True,
        )
    )
    raw = RewindCoachProgramme._serialize_ladder(ladder)
    restored = RewindCoachProgramme._deserialize_ladder(raw)
    assert restored is not None
    assert len(restored.can) == len(ladder.can)
    assert restored.can[0].id == ladder.can[0].id
    body = format_ladder_body(ladder)
    assert "Can rewind" in body
    assert "Cannot rewind" in body
    assert "Outside ADH" in body
