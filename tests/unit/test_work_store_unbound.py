"""Unbound work id must stay case-stable so resume picks persist."""

from __future__ import annotations

from src.adh_agents.runtime.work_models import UNBOUND_WORK_ID
from src.adh_agents.runtime.work_store import _normalize_work_id, work_key


def test_unbound_normalize_stable() -> None:
    assert _normalize_work_id("__unbound__") == UNBOUND_WORK_ID
    assert _normalize_work_id("__UNBOUND__") == UNBOUND_WORK_ID
    assert _normalize_work_id("") == UNBOUND_WORK_ID
    assert _normalize_work_id("INIT-REALWORLD-002") == "INIT-REALWORLD-002"
    assert _normalize_work_id("init-realworld-002") == "INIT-REALWORLD-002"


def test_unbound_work_key_not_uppercased() -> None:
    assert work_key("realworld", "adh.dev", UNBOUND_WORK_ID).endswith(":__unbound__")
    assert work_key("realworld", "adh.dev", "__UNBOUND__").endswith(":__unbound__")
    assert ":__UNBOUND__" not in work_key("realworld", "adh.dev", UNBOUND_WORK_ID)
