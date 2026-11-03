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


def parse_post_promote_gate(body: str) -> Optional[str]:
    """Lead tokens after promote: validate / clean / retry <hop>."""
    text = (body or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"validate", "clean", "stop"}:
        return lowered
    if lowered.startswith("retry "):
        hop = lowered[6:].strip()
        if hop in {"validate", "update", "impact"}:
            return f"retry:{hop}"
    return None


_VF_LINE = re.compile(r"^VF-?(\d+)\s*[:.\-]\s*(.+)$", re.I)
_VF_TOKEN = re.compile(r"VF-?\d+\s*[:.\-]", re.I)
_CHG_LINE = re.compile(r"^CHG-?(\d+)\s*[:.\-]\s*(.+)$", re.I)
_FINDING_CHOICES = {"fix", "accept", "reject", "defer", "explain"}
_MANIFEST_CHOICES = {"apply", "hold"}


def parse_finding_answers(body: str) -> Optional[dict[str, str]]:
    text = (body or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered == "accept-recs":
        return {"_accept_recs": "1"}
    if lowered == "stop":
        return {"_skip": "stop"}
    answers: dict[str, str] = {}
    saw = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if len(list(_VF_TOKEN.finditer(stripped))) > 1:
            return {"_invalid": "multi_vf_one_line"}
        match = _VF_LINE.match(stripped)
        if match is None:
            if saw:
                continue
            # "explain VF-03"
            explain = re.match(r"^explain\s+VF-?(\d+)\s*$", stripped, re.I)
            if explain:
                answers[f"VF-{int(explain.group(1)):02d}"] = "explain"
                saw = True
                continue
            return None
        saw = True
        key = f"VF-{int(match.group(1)):02d}"
        choice = strip_ask_rationale(match.group(2)).lower()
        if choice not in _FINDING_CHOICES:
            return {"_invalid": "choice_mismatch"}
        answers[key] = choice
    return answers or None


def validate_finding_answers(
    answers: dict[str, str],
    open_ids: list[str],
) -> Optional[str]:
    if answers.get("_skip") or answers.get("_invalid") or answers.get("_accept_recs"):
        return None
    allowed = {str(item).upper() for item in open_ids}
    for key in answers:
        if key.startswith("_"):
            continue
        if key.upper() not in allowed and key.upper().replace("VF-", "VF-") not in allowed:
            # normalize VF-3 vs VF-03
            compact = key.upper()
            if compact not in allowed:
                alt = f"VF-{int(compact.split('-')[1]):02d}" if "-" in compact else compact
                if alt not in allowed:
                    return "unknown_finding"
    return None


def parse_manifest_answer(body: str) -> Optional[dict[str, str]]:
    text = (body or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"apply", "hold", "stop"}:
        return {"_all": lowered if lowered != "stop" else "stop"}
    if lowered == "stop":
        return {"_all": "stop"}
    answers: dict[str, str] = {}
    saw = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _CHG_LINE.match(stripped)
        if match is None:
            if saw:
                continue
            return None
        saw = True
        key = f"CHG-{int(match.group(1)):02d}"
        choice = strip_ask_rationale(match.group(2)).lower()
        if choice not in _MANIFEST_CHOICES:
            return {"_invalid": "choice_mismatch"}
        answers[key] = choice
    return answers or None


def parse_impact_answer(body: str) -> Optional[str]:
    text = (body or "").strip().lower()
    if text in {"confirm", "revise", "stop"}:
        return text
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
