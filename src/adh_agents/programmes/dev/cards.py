"""Parse Hermes multi-thought Dev briefs via platform heading_sections."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.adh_agents.runtime.agentic_extract import heading_sections

_ADR = frozenset({"adr", "adr why"})
_API = frozenset({"api", "api why"})
_DEPS = frozenset({"deps", "dependencies"})
_VERIF = frozenset({"verification", "verification gaps"})
_CODING = frozenset({"coding readiness", "coding-readiness"})


@dataclass
class DevThoughtCard:
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
    sections = heading_sections(body or "")
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
