"""Lead message tokens: ask answers, promote picks, outline helpers (no regex)."""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from src.models.tenant_models import TenantContext


def outline_fingerprint(body: str) -> str:
    normalized = " ".join(body.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def ask_shaped_outline(body: str) -> bool:
    """True when any line looks like a fork answer ``F#:/./-``."""
    for line in (body or "").splitlines():
        if _fork_prefix(line.strip()) is not None:
            return True
    return False


def is_lead_outline_body(body: str, *, min_chars: int) -> bool:
    text = (body or "").strip()
    if len(text) < min_chars:
        return False
    if ask_shaped_outline(text):
        return False
    return True


def strip_ask_rationale(choice: str) -> str:
    """Drop trailing em-dash / en-dash / ' - ' rationale."""
    raw = (choice or "").strip()
    if not raw:
        return ""
    for sep in (" — ", " – ", " - "):
        if sep in raw:
            return raw.split(sep, 1)[0].strip() or raw
    return raw


def parse_ask_answers(body: str) -> Optional[dict[str, str]]:
    """Parse Lead fork answers (one ``F#:`` per line). No regex."""
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
        if _count_fork_tokens(stripped) > 1:
            return {"_invalid": "multi_f_one_line"}
        parsed = _parse_fork_line(stripped)
        if parsed is None:
            if saw_fork:
                continue
            return None
        saw_fork = True
        key, choice = parsed
        if key in answers:
            return {"_invalid": "duplicate_fork"}
        answers[key] = strip_ask_rationale(choice)
    return answers or None


def validate_ask_answers(
    answers: dict[str, str],
    forks: list[Any],
) -> Optional[str]:
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
    clean_suffix = False
    if " and clean" in lowered:
        clean_suffix = True
        if lowered.endswith(" and clean"):
            token = token[: -len(" and clean")].strip()
        lowered = token.lower()
    if lowered.startswith("promote "):
        token = token[8:].strip()
        lowered = token.lower()
    if lowered in {"none", "iterate", "skip"}:
        return lowered
    if _is_c_label(token):
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
    return (prefix or "").strip().rstrip("-").upper()


def initiative_example(prefix: str, number: int = 1) -> str:
    base = init_prefix_base(prefix)
    if not base:
        return f"INITIATIVE-{number:03d}"
    return f"{base}-{number:03d}"


def is_numbered_init(token: str, prefix: str) -> bool:
    base = init_prefix_base(prefix)
    body = (token or "").strip().upper()
    if not base or not body.startswith(base + "-"):
        return False
    rest = body[len(base) + 1 :]
    return bool(rest) and rest.isdigit()


def _is_numbered_init(token: str, tenant: TenantContext) -> bool:
    return is_numbered_init(token, tenant.init_prefix)


def extract_initiative(text: str, prefix: str) -> Optional[str]:
    """Pull ``{prefix}-{digits}`` from free text by token scan (no regex)."""
    base = init_prefix_base(prefix)
    if not base:
        return None
    needle = base + "-"
    for raw in (text or "").replace("/", " ").replace(",", " ").split():
        token = raw.strip().strip("()[]`\"'.,;:")
        upper = token.upper()
        if upper.startswith(needle) and is_numbered_init(upper, prefix):
            return upper
    return None


def coerce_init(proposed: str, prefix: str) -> str:
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
    trailing = _trailing_digits(token)
    if trailing is not None:
        return f"{base}-{trailing:03d}"
    return pending


def _coerce_init(proposed: str, slug: str) -> str:
    return coerce_init(proposed, f"INIT-{slug.upper()}-")


def _is_c_label(token: str) -> bool:
    t = (token or "").strip().upper()
    if len(t) < 2 or t[0] != "C":
        return False
    return t[1:].isdigit()


def _trailing_digits(token: str) -> int | None:
    digits = ""
    for ch in reversed(token or ""):
        if ch.isdigit():
            digits = ch + digits
        else:
            break
    if not digits:
        return None
    return int(digits)


def _fork_prefix(stripped: str) -> tuple[str, str] | None:
    """Return (Fn, remainder_after_sep) when line starts with F# sep."""
    return _parse_fork_line(stripped)


def _parse_fork_line(stripped: str) -> tuple[str, str] | None:
    s = (stripped or "").strip()
    if len(s) < 3 or (s[0] != "F" and s[0] != "f"):
        return None
    i = 1
    while i < len(s) and s[i].isdigit():
        i += 1
    if i == 1:
        return None
    num = s[1:i]
    rest = s[i:].lstrip()
    if not rest:
        return None
    sep = rest[0]
    if sep not in {":", ".", "-"}:
        return None
    choice = rest[1:].strip()
    if not choice:
        return None
    return f"F{num}", choice


def _count_fork_tokens(stripped: str) -> int:
    """Count F#-sep occurrences on one line (reject multi-F)."""
    count = 0
    parts = stripped.replace("\t", " ").split()
    # Also check contiguous: scan for F digit sep patterns
    i = 0
    s = stripped
    while i < len(s):
        if (s[i] == "F" or s[i] == "f") and i + 1 < len(s) and s[i + 1].isdigit():
            j = i + 1
            while j < len(s) and s[j].isdigit():
                j += 1
            k = j
            while k < len(s) and s[k].isspace():
                k += 1
            if k < len(s) and s[k] in {":", ".", "-"}:
                count += 1
                i = k + 1
                continue
        i += 1
    del parts
    return count
