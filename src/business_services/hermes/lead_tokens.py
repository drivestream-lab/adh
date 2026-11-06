"""Lead message tokens: ask answers, promote picks, outline classifier helpers."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from src.models.tenant_models import TenantContext

_FORK_LINE = re.compile(r"^F(\d+)\s*[:.\-]\s*(.+)$", re.I)
_FORK_TOKEN = re.compile(r"F\d+\s*[:.\-]", re.I)
_ASK_SHAPED = re.compile(r"^F\d+\s*[:.\-]", re.I | re.M)
_RATIONALE_TAIL = re.compile(r"\s+[—–\-]\s+.+$")
_PROMOTE_LABEL = re.compile(r"^C\d+$", re.I)


def outline_fingerprint(body: str) -> str:
    normalized = " ".join(body.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def ask_shaped_outline(body: str) -> bool:
    """True when the body looks like fork answers, not a product outline."""
    text = (body or "").strip()
    if not text:
        return False
    if _ASK_SHAPED.search(text):
        return True
    return False


def is_lead_outline_body(body: str, *, min_chars: int) -> bool:
    """Outline only if long enough and not ask-shaped (fork-answer class)."""
    text = (body or "").strip()
    if len(text) < min_chars:
        return False
    if ask_shaped_outline(text):
        return False
    return True


def strip_ask_rationale(choice: str) -> str:
    """Drop trailing ' — …' / ' - …' rationale from a fork choice line."""
    raw = (choice or "").strip()
    if not raw:
        return ""
    cleaned = _RATIONALE_TAIL.sub("", raw).strip()
    return cleaned or raw


def parse_ask_answers(body: str) -> Optional[dict[str, str]]:
    """Parse Lead fork answers.

    Returns:
      - None for chatter / empty
      - {"_skip": token} for stop/skip/provisional/none/timeout
      - {"_invalid": reason} for multi-F one-liners or malformed packs
      - {"F1": choice, ...} for valid one-fork-per-line answers
    """
    text = (body or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered == "stop":
        return {"_skip": "stop"}
    if lowered in {"skip", "provisional", "none", "timeout"}:
        return {"_skip": lowered}

    answers: dict[str, str] = {}
    saw_fork = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        matches = list(_FORK_TOKEN.finditer(stripped))
        if len(matches) > 1:
            return {"_invalid": "multi_f_one_line"}
        match = _FORK_LINE.match(stripped)
        if match is None:
            if saw_fork:
                # Trailing prose after forks is ignored; do not treat as chatter.
                continue
            return None
        saw_fork = True
        key = f"F{match.group(1)}"
        if key in answers:
            return {"_invalid": "duplicate_fork"}
        answers[key] = strip_ask_rationale(match.group(2))
    return answers or None


def validate_ask_answers(
    answers: dict[str, str],
    forks: list[Any],
) -> Optional[str]:
    """Return an error token if answers do not match frozen fork choice labels."""
    if answers.get("_skip") or answers.get("_invalid"):
        return None
    by_id: dict[str, list[str]] = {}
    for fork in forks:
        if not isinstance(fork, dict):
            continue
        fid = str(fork.get("id") or "").strip().upper()
        if not fid:
            continue
        labels = [str(item).strip() for item in (fork.get("choices") or []) if str(item).strip()]
        by_id[fid] = labels
    if not by_id:
        return None
    for key, value in answers.items():
        if key.startswith("_"):
            continue
        fid = key.upper()
        labels = by_id.get(fid)
        if labels is None:
            return "unknown_fork"
        if value not in labels:
            return "choice_mismatch"
    return None


def parse_promote_pick(body: str) -> Optional[str]:
    token = (body or "").strip()
    if not token:
        return None
    lowered = token.lower()
    # "C4 and clean" / "promote C4 and clean"
    clean_suffix = False
    if " and clean" in lowered:
        clean_suffix = True
        token = re.sub(r"\s+and\s+clean\s*$", "", token, flags=re.I).strip()
        token = re.sub(r"^promote\s+", "", token, flags=re.I).strip()
        lowered = token.lower()
    if lowered in {"none", "iterate", "skip"}:
        return lowered
    if _PROMOTE_LABEL.fullmatch(token):
        return f"{token.upper()}|clean" if clean_suffix else token.upper()
    normalized = token.replace("\\", "/")
    if "prd/reports/" in normalized and normalized.lower().endswith(".md"):
        return f"{token}|clean" if clean_suffix else token
    return None


def promote_pick_wants_clean(pick: str) -> tuple[str, bool]:
    raw = (pick or "").strip()
    if raw.endswith("|clean"):
        return raw[: -len("|clean")], True
    return raw, False


def lock_token(slug: str, fingerprint: str) -> str:
    return f"{slug}:{fingerprint}"


def init_prefix_base(prefix: str) -> str:
    """Normalised programme initiative prefix without a trailing dash."""
    return (prefix or "").strip().rstrip("-").upper()


def initiative_example(prefix: str, number: int = 1) -> str:
    """Example initiative id for Lead copy, derived from programme prefix."""
    base = init_prefix_base(prefix)
    if not base:
        return f"INITIATIVE-{number:03d}"
    return f"{base}-{number:03d}"


def is_numbered_init(token: str, prefix: str) -> bool:
    """True when token is ``{prefix}{digits}`` (prefix may include a trailing dash)."""
    base = init_prefix_base(prefix)
    body = (token or "").strip().upper()
    if not base or not body.startswith(base + "-"):
        return False
    rest = body[len(base) + 1 :]
    return bool(rest) and rest.isdigit()


def _is_numbered_init(token: str, tenant: TenantContext) -> bool:
    """Back-compat wrapper — prefer :func:`is_numbered_init` with ``tenant.init_prefix``."""
    return is_numbered_init(token, tenant.init_prefix)


def extract_initiative(text: str, prefix: str) -> Optional[str]:
    """Pull a numbered initiative matching the programme prefix from free text."""
    base = init_prefix_base(prefix)
    if not base:
        return None
    pattern = re.compile(rf"\b({re.escape(base)}-\d+)\b", re.I)
    match = pattern.search(text or "")
    if match is None:
        return None
    return match.group(1).upper()


def coerce_init(proposed: str, prefix: str) -> str:
    """Map a proposed id onto the programme prefix; PENDING when unusable."""
    base = init_prefix_base(prefix)
    if not base:
        raise ValueError("programme initiative prefix is missing")
    pending = f"{base}-PENDING"
    token = (proposed or "").strip().upper()
    if not token:
        return pending
    if is_numbered_init(token, prefix):
        return token
    if token.isdigit():
        return f"{base}-{int(token):03d}"
    if token.startswith(base + "-"):
        rest = token[len(base) + 1 :]
        if rest.isdigit():
            return f"{base}-{int(rest):03d}"
        return pending
    trailing = re.search(r"(\d+)$", token)
    if trailing:
        return f"{base}-{int(trailing.group(1)):03d}"
    return pending


def _coerce_init(proposed: str, slug: str) -> str:
    """Back-compat for tests — derive prefix from slug via TenantContext default shape."""
    return coerce_init(proposed, f"INIT-{slug.upper()}-")
