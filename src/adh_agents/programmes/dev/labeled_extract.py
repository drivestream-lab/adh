"""Agentic extract helpers — labeled lines only (no regex SSOT).

Hermes / Cursor are prompted to emit ``key: value`` lines. We extract those
keys and decide against an allow-list (catalogue outcomes or reply tokens).
"""

from __future__ import annotations

from typing import Optional, Sequence

from src.adh_agents.collaboration.human_replies import normalize_reply


def labeled_fields(body: str) -> dict[str, str]:
    """Parse ``key: value`` / ``key - value`` lines (first ``:`` or `` - `` wins)."""
    out: dict[str, str] = {}
    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("```"):
            continue
        key = ""
        value = ""
        if ":" in line:
            left, right = line.split(":", 1)
            key, value = left.strip().lower(), right.strip()
        elif " - " in line:
            left, right = line.split(" - ", 1)
            key, value = left.strip().lower(), right.strip()
        else:
            continue
        if not key or not value:
            continue
        # Keep first occurrence (agent often repeats).
        out.setdefault(key, value.strip().strip("`").strip("*").strip())
    return out


def extract_allowed(
    body: str,
    *,
    field: str,
    allowed: Sequence[str],
) -> Optional[str]:
    """Extract ``field`` then match against ``allowed`` via normalize_reply."""
    fields = labeled_fields(body)
    raw = (fields.get(field.lower()) or "").strip()
    if not raw:
        return None
    allowed_list = [a for a in allowed if (a or "").strip()]
    if not allowed_list:
        return None
    # Exact / alias match against allow-list (same SSOT as Lead briefs).
    matched = normalize_reply(raw, allowed_list)
    if matched:
        return matched
    # Case-insensitive exact among allowed.
    lowered = raw.lower()
    for tok in allowed_list:
        if tok.lower() == lowered:
            return tok
    return None


def extract_line(body: str, field: str) -> str:
    return labeled_fields(body).get(field.lower(), "")
