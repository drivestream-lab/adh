"""Platform agentic extract — labeled lines / headings (no regex SSOT).

All hired agents share this module. Hermes / Cursor are prompted to emit
``key: value`` lines or ``##`` section cards; we extract and match allow-lists.
"""

from __future__ import annotations

from typing import Optional, Sequence

from src.adh_agents.collaboration.human_replies import normalize_reply


def labeled_fields(body: str) -> dict[str, str]:
    """Parse ``key: value`` / ``key - value`` lines (first separator wins)."""
    out: dict[str, str] = {}
    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("```"):
            continue
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
        out.setdefault(key, _strip_marks(value))
    return out


def heading_sections(body: str) -> dict[str, str]:
    """Map ``## Title`` → body until next ``##`` (line-based)."""
    lines = (body or "").splitlines()
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
        out[title.lower()] = "\n".join(lines[start + 1 : end]).strip()
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
    return match_allowed(raw, allowed)


def extract_line(body: str, field: str) -> str:
    return labeled_fields(body).get(field.lower(), "")


def match_allowed(raw: str, allowed: Sequence[str]) -> Optional[str]:
    """Match a candidate string to an allow-list (normalize_reply + exact)."""
    allowed_list = [a for a in allowed if (a or "").strip()]
    if not allowed_list or not (raw or "").strip():
        return None
    matched = normalize_reply(raw, allowed_list)
    if matched:
        return matched
    lowered = raw.strip().lower()
    for tok in allowed_list:
        if tok.lower() == lowered:
            return tok
    return None


def parse_bullets_lines(section_body: str, *, max_bullets: int = 3) -> tuple[str, ...]:
    """Bullets starting with ``-`` / ``*``; plain prose → one bullet. No regex."""
    raw = (section_body or "").strip()
    if not raw:
        return ()
    lowered = raw.lower()
    if lowered in {"none", "n/a", "(none)", "- none"}:
        return ("none",)
    found: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            item = _clip(stripped[2:].strip(), 180)
            if item:
                found.append(item)
        if len(found) >= max_bullets:
            break
    if found:
        return tuple(found[:max_bullets])
    one = _clip(raw, 180)
    return (one,) if one else ()


def _strip_marks(value: str) -> str:
    return value.strip().strip("`").strip("*").strip()


def _clip(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def github_pull_number(pr_url: str) -> int | None:
    """Parse ``…/pull/N`` from a GitHub URL (string split, no regex)."""
    text = (pr_url or "").strip()
    marker = "/pull/"
    if marker not in text:
        return None
    rest = text.split(marker, 1)[1]
    digits = ""
    for ch in rest:
        if ch.isdigit():
            digits += ch
        else:
            break
    if not digits:
        return None
    return int(digits)


def find_init_token(body: str, *, prefix: str = "INIT-") -> Optional[str]:
    """First ``INIT-…`` token in free text (alnum/hyphen rest). No regex."""
    needle = (prefix or "INIT-").upper()
    if not needle:
        return None
    for raw in (body or "").replace("/", " ").replace(",", " ").split():
        token = raw.strip().strip("()[]`\"'.,;:")
        upper = token.upper()
        if not upper.startswith(needle):
            continue
        rest = upper[len(needle) :]
        if rest and all(ch.isalnum() or ch == "-" for ch in rest):
            return upper
    return None


def first_vf_id(text: str) -> Optional[str]:
    """First ``VF-NN`` / ``VFNN`` id in a line. No regex."""
    lower = (text or "").lower()
    i = 0
    while True:
        idx = lower.find("vf", i)
        if idx < 0:
            return None
        if idx > 0 and (lower[idx - 1].isalnum() or lower[idx - 1] == "_"):
            i = idx + 2
            continue
        rest = text[idx + 2 :]
        if rest[:1] in {"-", "–"}:
            rest = rest[1:]
        digits = ""
        for ch in rest:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            i = idx + 2
            continue
        after = rest[len(digits) : len(digits) + 1]
        if after and (after.isalnum() or after == "_"):
            i = idx + 2
            continue
        return f"VF-{int(digits):02d}"
