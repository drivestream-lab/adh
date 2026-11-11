"""Parse Hermes multi-thought Dev briefs (ADR / API / deps / verification)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

_SECTION = re.compile(
    r"(?im)^##\s+(ADR(?:\s+why)?|API(?:\s+why)?|Deps|Dependencies|Verification(?:\s+gaps)?|Coding\s*readiness)\s*$"
)


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
    """Parse ## ADR / API / Deps / Verification sections. None if empty/malformed."""
    text = (body or "").strip()
    if not text:
        return None
    matches = list(_SECTION.finditer(text))
    if not matches:
        return None
    card = DevThoughtCard()
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = match.group(1).strip().lower()
        content = text[start:end].strip()
        card.raw_sections[title] = content
        if title.startswith("adr"):
            card.adr_why = content
        elif title.startswith("api"):
            card.api_why = content
        elif title.startswith("dep"):
            card.deps = content
        elif title.startswith("verif"):
            card.verification_gaps = content
        elif title.startswith("coding"):
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
