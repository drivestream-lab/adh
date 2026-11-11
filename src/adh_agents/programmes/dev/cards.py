"""Parse Hermes multi-thought Dev briefs — ``##`` headings (no regex)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Exact heading titles Hermes is prompted to emit (lowercase).
_ADR = frozenset({"adr", "adr why"})
_API = frozenset({"api", "api why"})
_DEPS = frozenset({"deps", "dependencies"})
_VERIF = frozenset({"verification", "verification gaps"})
_CODING = frozenset({"coding readiness", "coding-readiness"})


@dataclass
class DevThoughtCard:
    """Structured multi-thought card extracted from Hermes copy."""

    adr_why: str = ""
    api_why: str = ""
    deps: str = ""
    verification_gaps: str = ""
    coding_readiness: str = ""
    raw_sections: dict[str, str] = field(default_factory=dict)

    @property
    def has_any(self) -> bool:
        return bool(
            self.adr_why
            or self.api_why
            or self.deps
            or self.verification_gaps
            or self.coding_readiness
        )


def parse_dev_thought_card(body: str) -> Optional[DevThoughtCard]:
    """Split on ``##`` headings; map known titles. None if empty/malformed."""
    text = (body or "").strip()
    if not text:
        return None
    sections = _heading_sections(text)
    if not sections:
        return None
    card = DevThoughtCard(raw_sections=dict(sections))
    for title, content in sections.items():
        key = title.lower().strip()
        if key in _ADR:
            card.adr_why = content
        elif key in _API:
            card.api_why = content
        elif key in _DEPS:
            card.deps = content
        elif key in _VERIF:
            card.verification_gaps = content
        elif key in _CODING:
            card.coding_readiness = content
    return card if card.has_any else None


def card_bluf(card: DevThoughtCard) -> str:
    """One-line BLUF for coach from the richest section."""
    for label, value in (
        ("ADR", card.adr_why),
        ("API", card.api_why),
        ("Deps", card.deps),
        ("Verification", card.verification_gaps),
        ("Coding-ready", card.coding_readiness),
    ):
        if value:
            first = value.splitlines()[0].strip()
            return f"{label}: {first[:160]}"
    return "Review engg think cards before accepting."


def _heading_sections(text: str) -> dict[str, str]:
    """Map ``## Title`` → body until next ``##`` (line-based, no regex)."""
    lines = (text or "").splitlines()
    titles: list[tuple[str, int]] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("###"):
            titles.append((stripped[3:].strip(), idx))
    if not titles:
        return {}
    out: dict[str, str] = {}
    for i, (title, start) in enumerate(titles):
        end = titles[i + 1][1] if i + 1 < len(titles) else len(lines)
        body = "\n".join(lines[start + 1 : end]).strip()
        out[title] = body
    return out
