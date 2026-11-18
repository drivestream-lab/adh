"""Unbound work id must stay case-stable so resume picks persist."""

from __future__ import annotations

from src.adh_agents.runtime.work_models import UNBOUND_WORK_ID, AgentWorkSession
from src.adh_agents.runtime.work_store import _normalize_work_id, _work_id_part, work_key


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


def test_work_id_part_prefers_explicit_repo_scoped_id() -> None:
    """Coder hire sets work_id=INIT:repo + initiative=INIT — must not collapse to INIT."""
    session = AgentWorkSession(
        tenant_slug="realworld",
        role_id="adh.coder",
        room="engg",
        work_id="INIT-REALWORLD-001:realworld-api",
        initiative="INIT-REALWORLD-001",
        stage="learning-extract",
    )
    assert _work_id_part(session) == "INIT-REALWORLD-001:REALWORLD-API"


def test_work_id_part_falls_back_to_initiative_when_unbound() -> None:
    session = AgentWorkSession(
        tenant_slug="realworld",
        role_id="adh.pm",
        room="ops",
        work_id=UNBOUND_WORK_ID,
        initiative="INIT-A",
        stage="validate-requirements",
    )
    assert _work_id_part(session) == "INIT-A"
