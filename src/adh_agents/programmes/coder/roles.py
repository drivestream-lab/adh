"""Coder Buzz handle helpers — ``adh.coder`` / ``adh.coder.<repo>`` (C.1 / C.13)."""

from __future__ import annotations

_CODER_PREFIX = "adh.coder"


def short_repo(value: str) -> str:
    return (value or "").strip().rsplit("/", 1)[-1]


def coder_role_for_repo(repo: str) -> str:
    """Buzz handle for a repo-scoped coder baton (no hardcoded repo lists)."""
    name = short_repo(repo)
    if not name:
        raise ValueError("coder role needs a non-empty repo suffix")
    return f"{_CODER_PREFIX}.{name}"


def is_coder_role(role_id: str) -> bool:
    role = (role_id or "").strip()
    return role == _CODER_PREFIX or role.startswith(f"{_CODER_PREFIX}.")


def coder_role_prefix() -> str:
    return _CODER_PREFIX
