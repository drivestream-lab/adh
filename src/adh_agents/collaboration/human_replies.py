"""Human-sounding Buzz reply phrases + aliases (programme SSOT for Lead tokens)."""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

# Canonical phrases humans should see on Buzz.
MERGE_PRODUCT_PR = "merge the product PR"
PARK = "park"
NEED_ANOTHER_ROUND = "need another round"
ARCHIVE_TASK = "archive task"
DELETE_TASK = "delete task"
KEEP_OPEN = "keep open"
REWIND = "rewind"
CONFIRM_REWIND = "confirm rewind"
CANCEL_REWIND = "cancel"
TRAJ = "traj"

# Dev YAML development (E1)
ANOTHER_ROUND = "another round"
ACCEPT_TDD_ADR = "accept tdd-adr"
CODING_READY = "coding ready"
MERGE_SPEC_PR = "merge the spec PR"
AUTHORIZE_BOARD = "authorize board"
RESEED_BOARD = "reseed board"
REVISE_ENGG = "revise engg"
HOLD = "hold"

# Canonical → accepted aliases (case-insensitive match on full line / prefix).
_ALIASES: dict[str, tuple[str, ...]] = {
    MERGE_PRODUCT_PR: (
        MERGE_PRODUCT_PR,
        "go ahead",
        "authorize prd_merge",
        "authorize",
        "merge",
    ),
    PARK: (PARK, "hold"),
    NEED_ANOTHER_ROUND: (NEED_ANOTHER_ROUND, "new_round", "round_again"),
    ARCHIVE_TASK: (ARCHIVE_TASK, "archive"),
    DELETE_TASK: (DELETE_TASK, "delete"),
    KEEP_OPEN: (KEEP_OPEN, "keep"),
    REWIND: (REWIND,),
    CONFIRM_REWIND: (CONFIRM_REWIND, "confirm"),
    CANCEL_REWIND: (CANCEL_REWIND, "cancel rewind"),
    TRAJ: (TRAJ, "trajectory", "show trajectory"),
    ANOTHER_ROUND: (ANOTHER_ROUND, NEED_ANOTHER_ROUND, "new_round", "round_again"),
    ACCEPT_TDD_ADR: (ACCEPT_TDD_ADR, "accept adr", "accept tdd", "accept technical review"),
    CODING_READY: (CODING_READY, "coding-ready", "ready for board"),
    MERGE_SPEC_PR: (MERGE_SPEC_PR, "merge spec", "merge the spec prs", "authorize spec_merge"),
    AUTHORIZE_BOARD: (AUTHORIZE_BOARD, "seed board", "create board tickets"),
    RESEED_BOARD: (
        RESEED_BOARD,
        "re-seed board",
        "seed board again",
        "reseed tickets",
    ),
    REVISE_ENGG: (REVISE_ENGG, "revise engineering", "reopen engg"),
    HOLD: (HOLD, PARK),
}


def merge_gate_tokens() -> list[str]:
    """Reply tokens for post-rally product merge coach."""
    return [MERGE_PRODUCT_PR, "go ahead", PARK]


def merge_gate_wills() -> dict[str, str]:
    return {
        MERGE_PRODUCT_PR: "undraft + merge the product PR, sync local develop, hand off to KB",
        "go ahead": "same as merge the product PR",
        PARK: "park — nothing lands",
    }


def expand_aliases(canonical: str) -> tuple[str, ...]:
    key = (canonical or "").strip().lower()
    for canon, aliases in _ALIASES.items():
        if canon.lower() == key:
            return aliases
    return ((canonical or "").strip(),)


def normalize_reply(body: str, allowed: Sequence[str]) -> Optional[str]:
    """Match Lead body to one *allowed* token, honouring aliases.

    Returns the **allowed** token string (as listed on the brief), not a private id.
    """
    lines = [ln.strip().lower() for ln in (body or "").splitlines() if ln.strip()]
    if not lines:
        return None
    allowed_list = [a for a in allowed if (a or "").strip()]
    if not allowed_list:
        return None

    # Build alias → preferred allowed token.
    alias_to_allowed: dict[str, str] = {}
    for allowed_tok in allowed_list:
        # Direct
        alias_to_allowed[allowed_tok.strip().lower()] = allowed_tok
        # If allowed is canonical or alias of a family, map whole family → this allowed tok
        for canon, aliases in _ALIASES.items():
            family = {canon.lower(), *(a.lower() for a in aliases)}
            if allowed_tok.strip().lower() in family:
                for alias in family:
                    alias_to_allowed.setdefault(alias, allowed_tok)

    for line in lines:
        if line in alias_to_allowed:
            return alias_to_allowed[line]
        for alias, allowed_tok in alias_to_allowed.items():
            if line.startswith(alias):
                return allowed_tok
    return None


def tokens_equivalent(a: str, b: str) -> bool:
    """True when two reply strings belong to the same alias family."""
    left = (a or "").strip().lower()
    right = (b or "").strip().lower()
    if left == right:
        return True
    for aliases in _ALIASES.values():
        family = {x.lower() for x in aliases}
        if left in family and right in family:
            return True
    return False


def strip_legacy_ack(tokens: Iterable[str]) -> list[str]:
    """Drop dead mid-rally tokens from any list (defense in depth)."""
    banned = {"ack_pe", "ack pe"}
    return [t for t in tokens if (t or "").strip().lower() not in banned]
