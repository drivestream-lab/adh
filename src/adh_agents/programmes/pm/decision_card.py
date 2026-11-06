"""Hermes PM decision cards — product-focused promote + post-PM delta briefs."""

from __future__ import annotations

import re
from typing import NamedTuple, Optional, Sequence

_SECTION_RE = re.compile(
    r"^##\s+(bluf|locking|not_locking|revise_if|changed|deferred|still_risky|example|options)"
    r"\s*\n(.*?)(?=^##\s+|\Z)",
    re.I | re.M | re.S,
)
_RECOMMEND_CN = re.compile(r"^recommend\s*:\s*(C\d+)\s*$", re.I | re.M)
_RECOMMEND_POSTPM = re.compile(r"^recommend\s*:\s*(confirm|revise)\s*$", re.I | re.M)
_BULLET = re.compile(r"^\s*[-*]\s+(.+?)\s*$", re.M)

_MAX_BULLETS = 3
_BLUF_LIMIT = 200
_EXAMPLE_LIMIT = 400
_BULLET_LIMIT = 180

CARD_PROMOTE = "promote"
CARD_POSTPM = "postpm"


class DecisionCard(NamedTuple):
    """Product decision card for a human PM.

    Promote uses locking / not_locking / revise_if (buying / not buying / other pick).
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
        """Back-compat alias for Buzz/session."""
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
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def parse_bullets(section_body: str, *, max_bullets: int = _MAX_BULLETS) -> tuple[str, ...]:
    """Extract markdown bullets; plain non-empty prose becomes one bullet."""
    raw = (section_body or "").strip()
    if not raw:
        return ()
    lowered = raw.lower()
    if lowered in {"none", "n/a", "(none)", "- none"}:
        return ("none",)
    found = [clip_card_text(m.group(1), limit=_BULLET_LIMIT) for m in _BULLET.finditer(raw)]
    found = [b for b in found if b]
    if found:
        return tuple(found[:max_bullets])
    one = clip_card_text(raw, limit=_BULLET_LIMIT)
    return (one,) if one else ()


def _sections(body: str) -> dict[str, str]:
    return {m.group(1).lower(): m.group(2).strip() for m in _SECTION_RE.finditer(body or "")}


def _bullets_or_none(sections: dict[str, str], key: str, *, default_none: bool) -> tuple[str, ...]:
    raw = (sections.get(key) or "").strip()
    if not raw:
        return ("none",) if default_none else ()
    parsed = parse_bullets(raw)
    if not parsed and default_none:
        return ("none",)
    return parsed


def parse_promote_decision_card(
    body: str,
    *,
    allowed_labels: Optional[Sequence[str]] = None,
) -> Optional[DecisionCard]:
    """Parse promote brief (buying / not buying / pick-another). None if malformed."""
    text = (body or "").strip()
    if not text:
        return None
    match = _RECOMMEND_CN.search(text)
    if match is None:
        return None
    recommend = match.group(1).upper()
    allowed = {str(x).upper() for x in (allowed_labels or ()) if str(x).strip()}
    if allowed and recommend not in allowed:
        return None
    sections = _sections(text)
    bluf = clip_card_text(sections.get("bluf") or "", limit=_BLUF_LIMIT)
    example = clip_card_text(sections.get("example") or "", limit=_EXAMPLE_LIMIT)
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
    """Parse post-PM delta brief (changed / deferred / still risky). None if malformed."""
    text = (body or "").strip()
    if not text:
        return None
    match = _RECOMMEND_POSTPM.search(text)
    if match is None:
        return None
    recommend = match.group(1).strip().lower()
    sections = _sections(text)
    bluf = clip_card_text(sections.get("bluf") or "", limit=_BLUF_LIMIT)
    example = clip_card_text(sections.get("example") or "", limit=_EXAMPLE_LIMIT)
    if not bluf or not example:
        return None
    # Delta card quality bar: require changed + deferred + still_risky sections.
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
    example: str,
    locking: Sequence[str] = (),
    not_locking: Sequence[str] = (),
    revise_if: Sequence[str] = ("none",),
    card_kind: str = CARD_PROMOTE,
) -> DecisionCard:
    """Build a card (fallbacks / synthetic)."""
    lock = tuple(clip_card_text(str(x), limit=_BULLET_LIMIT) for x in locking if str(x).strip())[
        :_MAX_BULLETS
    ]
    nlock = tuple(
        clip_card_text(str(x), limit=_BULLET_LIMIT) for x in not_locking if str(x).strip()
    )[:_MAX_BULLETS]
    rev = tuple(clip_card_text(str(x), limit=_BULLET_LIMIT) for x in revise_if if str(x).strip())[
        :_MAX_BULLETS
    ]
    if not rev:
        rev = ("none",)
    return DecisionCard(
        recommend=recommend,
        bluf=clip_card_text(bluf),
        locking=lock,
        not_locking=nlock,
        revise_if=rev,
        example=clip_card_text(example, limit=_EXAMPLE_LIMIT),
        card_kind=card_kind,
    )
