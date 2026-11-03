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
    """Outline only if long enough and not ask-shaped (INIT-002 class)."""
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
    if lowered in {"none", "iterate", "skip"}:
        return lowered
    if _PROMOTE_LABEL.fullmatch(token):
        return token.upper()
    normalized = token.replace("\\", "/")
    if "prd/reports/" in normalized and normalized.lower().endswith(".md"):
        return token
    return None


def lock_token(slug: str, fingerprint: str) -> str:
    return f"{slug}:{fingerprint}"


def _is_numbered_init(token: str, tenant: TenantContext) -> bool:
    prefix = tenant.init_prefix.upper()
    body = (token or "").strip().upper()
    if not prefix or not body.startswith(prefix):
        return False
    rest = body[len(prefix) :]
    return bool(rest) and rest.isdigit()


def _coerce_init(proposed: str, slug: str) -> str:
    prefix = f"INIT-{slug.upper()}-"
    token = (proposed or "").strip().upper()
    if not token.startswith("INIT-"):
        return f"{prefix}PENDING"
    rest = token[len("INIT-") :]
    for drop in (f"{slug.upper()}-", "RW-", "ADH-"):
        if rest.startswith(drop):
            rest = rest[len(drop) :]
            break
    rest = re.sub(r"[^A-Z0-9-]", "", rest).strip("-")
    if not rest or rest == "PENDING":
        return f"{prefix}PENDING"
    return f"{prefix}{rest}"
