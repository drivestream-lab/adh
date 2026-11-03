"""Redis key helpers and TTL policy for Hermes PM pending Lead waits."""

from __future__ import annotations


def pending_ask_key(slug: str) -> str:
    return f"adh:pm:awaiting-ask:{slug}"


def pending_recommend_key(slug: str) -> str:
    return f"adh:pm:awaiting-recommend:{slug}"


def pending_init_key(slug: str) -> str:
    return f"adh:pm:awaiting-init:{slug}"


def inflight_lock_key(slug: str, fingerprint: str) -> str:
    return f"adh:pm:inflight:{slug}:{fingerprint}"


def ask_pending_ttl_seconds(
    *, ask_wait_seconds: float, outline_lock_seconds: int, grace_seconds: int
) -> int:
    """Keep ask durable past the wait window so expiry cannot free an outline slot."""
    wait = max(0, int(ask_wait_seconds))
    grace = max(0, int(grace_seconds))
    lock = max(60, int(outline_lock_seconds))
    return max(lock, wait + grace)
