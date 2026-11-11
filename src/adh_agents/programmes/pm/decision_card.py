"""Hermes PM decision cards — platform heading/labeled extract (no regex)."""

from __future__ import annotations

from typing import NamedTuple, Optional, Sequence

from src.adh_agents.runtime.agentic_extract import (
    extract_allowed,
    extract_line,
    heading_sections,
    parse_bullets_lines,
)

_BLUF_LIMIT = 200
_EXAMPLE_LIMIT = 400

CARD_PROMOTE = "promote"
CARD_POSTPM = "postpm"


class DecisionCard(NamedTuple):
    """Product decision card for a human PM.

    Promote uses locking / not_locking / revise_if.
    Post-PM uses the same tuple slots for changed / deferred / still_risky.
    """

    recommend: str
    bluf: str
    locking: tuple[str, ...]
    not_locking: tuple[str, ...]
    revise_if: tuple[str, ...]
    example: str
    card_kind: str = CARD_PROMOTE

    @property
    def recommend_why(self) -> str:
        return self.bluf

    @property
    def changed(self) -> tuple[str, ...]:
        return self.locking if self.card_kind == CARD_POSTPM else ()

    @property
    def deferred(self) -> tuple[str, ...]:
        return self.not_locking if self.card_kind == CARD_POSTPM else ()

    @property
    def still_risky(self) -> tuple[str, ...]:
        return self.revise_if if self.card_kind == CARD_POSTPM else ()


def clip_card_text(text: str, *, limit: int = _BLUF_LIMIT) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def parse_bullets(section_body: str, *, max_bullets: int = 3) -> tuple[str, ...]:
    return parse_bullets_lines(section_body, max_bullets=max_bullets)


def parse_promote_decision_card(
    body: str,
    *,
    allowed_labels: Optional[Sequence[str]] = None,
) -> Optional[DecisionCard]:
    """Parse promote brief. None if malformed."""
    text = (body or "").strip()
    if not text:
        return None
    allowed = [str(x).upper() for x in (allowed_labels or ()) if str(x).strip()]
    # Prefer labeled recommend:; also accept C* from allow-list via extract.
    recommend_raw = extract_line(text, "recommend")
    if not recommend_raw and allowed:
        # Fall through: look for first allowed label as whole-line token.
        for line in text.splitlines():
            cand = line.strip().upper()
            if cand in allowed:
                recommend_raw = cand
                break
    if not recommend_raw:
        return None
    recommend = recommend_raw.strip().upper()
    if allowed and recommend not in {a.upper() for a in allowed}:
        # Try normalize against allowed as-is.
        matched = extract_allowed(
            f"recommend: {recommend_raw}", field="recommend", allowed=list(allowed_labels or [])
        )
        if not matched:
            return None
        recommend = matched.upper()
    sections = heading_sections(text)
    bluf = clip_card_text(
        sections.get("bluf") or extract_line(text, "bluf") or "", limit=_BLUF_LIMIT
    )
    example = clip_card_text(
        sections.get("example") or extract_line(text, "example") or "",
        limit=_EXAMPLE_LIMIT,
    )
    if not bluf or not example:
        return None
    return DecisionCard(
        recommend=recommend,
        bluf=bluf,
        locking=_bullets_or_none(sections, "locking", default_none=False),
        not_locking=_bullets_or_none(sections, "not_locking", default_none=True),
        revise_if=_bullets_or_none(sections, "revise_if", default_none=True),
        example=example,
        card_kind=CARD_PROMOTE,
    )


def parse_postpm_decision_card(body: str) -> Optional[DecisionCard]:
    """Parse post-PM delta brief (confirm / revise). None if malformed."""
    text = (body or "").strip()
    if not text:
        return None
    recommend = extract_allowed(text, field="recommend", allowed=["confirm", "revise"])
    if recommend is None:
        return None
    sections = heading_sections(text)
    bluf = clip_card_text(
        sections.get("bluf") or extract_line(text, "bluf") or "", limit=_BLUF_LIMIT
    )
    example = clip_card_text(
        sections.get("example") or extract_line(text, "example") or "",
        limit=_EXAMPLE_LIMIT,
    )
    if not bluf or not example:
        return None
    if not all(k in sections for k in ("changed", "deferred", "still_risky")):
        return None
    return DecisionCard(
        recommend=recommend,
        bluf=bluf,
        locking=_bullets_or_none(sections, "changed", default_none=False),
        not_locking=_bullets_or_none(sections, "deferred", default_none=True),
        revise_if=_bullets_or_none(sections, "still_risky", default_none=True),
        example=example,
        card_kind=CARD_POSTPM,
    )


def decision_card(
    *,
    recommend: str,
    bluf: str,
    locking: Sequence[str] = (),
    not_locking: Sequence[str] = (),
    revise_if: Sequence[str] = (),
    example: str = "",
    card_kind: str = CARD_PROMOTE,
) -> DecisionCard:
    return DecisionCard(
        recommend=recommend,
        bluf=clip_card_text(bluf),
        locking=tuple(locking),
        not_locking=tuple(not_locking) or ("none",),
        revise_if=tuple(revise_if) or ("none",),
        example=clip_card_text(example, limit=_EXAMPLE_LIMIT),
        card_kind=card_kind,
    )


def _bullets_or_none(sections: dict[str, str], key: str, *, default_none: bool) -> tuple[str, ...]:
    raw = (sections.get(key) or "").strip()
    if not raw:
        return ("none",) if default_none else ()
    parsed = parse_bullets(raw)
    if not parsed and default_none:
        return ("none",)
    return parsed
