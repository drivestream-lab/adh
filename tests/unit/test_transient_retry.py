"""Transient network retry helper."""

from __future__ import annotations

import httpx
import pytest

from src.utils.transient_retry import is_transient_error, retry_transient

# pytest-asyncio auto mode


async def test_retry_succeeds_on_second_attempt() -> None:
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("boom")
        return "ok"

    attempts: list[int] = []

    async def on_attempt(n: int, max_n: int, exc: BaseException) -> None:
        attempts.append(n)
        assert max_n == 3
        assert "boom" in str(exc)

    assert (
        await retry_transient(flaky, attempts=3, backoff_seconds=0.01, on_attempt=on_attempt)
        == "ok"
    )
    assert calls["n"] == 2
    assert attempts == [1]


async def test_retry_exhausts_and_reraises() -> None:
    async def always() -> str:
        raise httpx.ConnectError("down")

    with pytest.raises(httpx.ConnectError):
        await retry_transient(always, attempts=2, backoff_seconds=0.01)


def test_non_transient_raises_immediately() -> None:
    assert is_transient_error(httpx.ConnectError("x"))
    assert not is_transient_error(ValueError("nope"))
