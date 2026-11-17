"""Verify Buzz handle helpers — ``adh.verify`` (V.18 single worker)."""

from __future__ import annotations

_VERIFY_ROLE = "adh.verify"


def is_verify_role(role_id: str) -> bool:
    return (role_id or "").strip() == _VERIFY_ROLE


def verify_role() -> str:
    return _VERIFY_ROLE
