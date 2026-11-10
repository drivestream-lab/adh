"""God mode: after promote, chain meta-pm — no Lead ``post-pm`` token."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.adh_agents.programmes.pm.authoring import AuthoringProgrammeService
from src.adh_agents.runtime.autonomy import AutonomyPolicy
from src.adh_agents.runtime.work_models import AWAITING_JUDGMENT, AgentWorkSession
from src.adh_agents.settings import AdhAutonomySettings
from src.configs.base_settings import BaseSettings
from src.models.buzz_models import TaskState
from src.models.hermes.intent_models import JudgmentRequest
from src.models.tenant_models import TenantContext


def _reset_autonomy() -> None:
    BaseSettings._instances.pop(AdhAutonomySettings.__name__, None)


def _tenant() -> TenantContext:
    return TenantContext(
        slug="realworld",
        org="10xScale-AILabs",
        meta_repo="realworld-meta",
        meta_root="/tmp/realworld-meta",
        init_prefix="INIT-REALWORLD-",
        ops_room="realworld-ops",
    )


def _svc(
    *, autonomy: AutonomyPolicy
) -> tuple[AuthoringProgrammeService, AsyncMock, AsyncMock, AsyncMock]:
    store = MagicMock()
    store.clear = AsyncMock()
    store.load = AsyncMock(return_value=None)
    store.save = AsyncMock()
    dispatch = MagicMock()
    briefs = MagicMock()
    poster = MagicMock()
    post_status = AsyncMock()
    poster.post_status = post_status
    poster.copy = MagicMock(return_value="Promoted — reply post-pm")
    workspace = MagicMock()
    workspace.read_local = MagicMock(return_value="# PRD\n")
    workspace.write_local = MagicMock()
    buzz = MagicMock()
    set_task_state = AsyncMock()
    buzz.set_task_state = set_task_state
    gates = MagicMock()
    meta_pm = MagicMock()
    start_programme = AsyncMock()
    meta_pm.start_programme = start_programme
    meta_pm.resume_programme = AsyncMock()
    svc = AuthoringProgrammeService(
        store,
        dispatch,
        briefs,
        poster,
        workspace,
        buzz,
        gates,
        autonomy,
        meta_pm,
    )
    return svc, start_programme, post_status, set_task_state


def test_god_promote_chains_meta_pm(monkeypatch) -> None:
    monkeypatch.setenv("ADH_AUTONOMY_MODE", "god")
    _reset_autonomy()
    redis = MagicMock()
    redis.set = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    autonomy = AutonomyPolicy(redis)
    svc, start_programme, post_status, set_task_state = _svc(autonomy=autonomy)
    session = AgentWorkSession(
        tenant_slug="realworld",
        role_id="adh.pm",
        room="task-init-realworld-004",
        initiative="INIT-REALWORLD-004",
        programme="authoring",
        stage="authoring-promote",
        awaiting=AWAITING_JUDGMENT,
        open_brief=JudgmentRequest(
            node_id="authoring-promote",
            purpose="authoring-promote",
            question="pick?",
            recommend="C4",
            reply_tokens=["C4", "skip"],
        ),
        slots={"authoring_promote_paths": '{"C4":"prd/reports/INIT-REALWORLD-004-prd-think-4.md"}'},
    )

    async def _run() -> bool:
        return await svc._on_promote_reply(_tenant(), session.room, session, "C4")

    assert asyncio.run(_run()) is True
    start_programme.assert_awaited()
    # Human-only copy must not be used when god chains.
    human_bodies = [c.args[1] for c in post_status.await_args_list if len(c.args) > 1]
    assert any("God chaining" in b for b in human_bodies)
    assert not any("post-pm INIT" in b for b in human_bodies)
    set_task_state.assert_awaited()
    assert set_task_state.await_args is not None
    assert set_task_state.await_args.args[2] == TaskState.RUNNING
    _reset_autonomy()


def test_human_promote_still_asks_post_pm(monkeypatch) -> None:
    monkeypatch.setenv("ADH_AUTONOMY_MODE", "human")
    _reset_autonomy()
    redis = MagicMock()
    autonomy = AutonomyPolicy(redis)
    svc, start_programme, post_status, _set_task_state = _svc(autonomy=autonomy)
    session = AgentWorkSession(
        tenant_slug="realworld",
        role_id="adh.pm",
        room="task-init-realworld-004",
        initiative="INIT-REALWORLD-004",
        programme="authoring",
        stage="authoring-promote",
        awaiting=AWAITING_JUDGMENT,
        open_brief=JudgmentRequest(
            node_id="authoring-promote",
            purpose="authoring-promote",
            question="pick?",
            recommend="C4",
            reply_tokens=["C4", "skip"],
        ),
        slots={"authoring_promote_paths": '{"C4":"prd/reports/INIT-REALWORLD-004-prd-think-4.md"}'},
    )

    async def _run() -> bool:
        return await svc._on_promote_reply(_tenant(), session.room, session, "C4")

    assert asyncio.run(_run()) is True
    start_programme.assert_not_awaited()
    post_status.assert_awaited()
    _reset_autonomy()
