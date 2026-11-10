"""KB enrich land gate — coach + land_pull_request on authorize (no forge-click)."""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.delivery_voice import forbidden_buzz_hits
from src.adh_agents.programmes.kb.enrich import KbEnrichProgramme
from src.adh_agents.runtime.work_models import AWAITING_JUDGMENT, AgentWorkSession
from src.models.buzz_models import EventType
from src.models.hermes.execution_models import ForgeActionResult
from src.models.tenant_models import TenantContext


class _FakePoster:
    def __init__(self) -> None:
        self.posts: list[tuple[str, EventType, dict[str, Any]]] = []

    async def post_status(
        self,
        room: str,
        body: str,
        event_type: EventType = EventType.PROGRESS,
        payload: Optional[dict[str, Any]] = None,
        *,
        identity_handle: str | None = None,
    ) -> None:
        del room, identity_handle
        self.posts.append((body, event_type, payload or {}))

    async def post_human_next(self, room: str, **kwargs: Any) -> None:
        from src.adh_agents.collaboration.gate_coach import format_human_next

        body = format_human_next(
            i_did=kwargs.get("i_did", ""),
            recommend=kwargs.get("recommend", ""),
            outside_adh=kwargs.get("outside_adh", ""),
            tokens=list(kwargs.get("tokens") or []),
            recommend_why=kwargs.get("recommend_why", ""),
            evidence=kwargs.get("evidence", ""),
            human_role=kwargs.get("human_role", "Lead"),
            hop=kwargs.get("hop", ""),
            example=kwargs.get("example", ""),
        )
        await self.post_status(
            room,
            body,
            kwargs.get("event_type", EventType.PROGRESS),
            kwargs.get("payload") or {},
            identity_handle=kwargs.get("identity_handle"),
        )


@pytest.mark.asyncio
async def test_open_land_gate_coach_forbids_forge_click() -> None:
    poster = _FakePoster()
    prog = object.__new__(KbEnrichProgramme)
    prog.role_id = "adh.kb"
    prog._poster = poster  # type: ignore[attr-defined]
    prog._briefs = HermesBriefService()  # type: ignore[attr-defined]
    prog._store = AsyncMock()  # type: ignore[attr-defined]

    tenant = TenantContext(
        slug="demo",
        org="org",
        meta_repo="demo-meta",
        meta_root="/tmp/demo-meta",
        ops_room="demo-ops",
        integration_branch="develop",
        init_prefix="INIT-",
    )
    session = AgentWorkSession(
        tenant_slug="demo",
        role_id="adh.kb",
        room="demo-ops",
        work_id="KB-INIT-1",
        initiative="INIT-1",
        programme="kb-enrich",
        stage="kb-enrich-authorize",
        slots={},
    )
    await prog._open_land_gate(  # type: ignore[attr-defined]
        tenant,
        "demo-ops",
        session,
        init="INIT-1",
        pr_url="https://github.com/org/demo-meta/pull/9",
        pr_number=9,
    )
    assert session.stage == "kb-enrich-land"
    assert session.awaiting == AWAITING_JUDGMENT
    assert session.open_brief is not None
    body = poster.posts[-1][0]
    assert "**I did.**" in body
    assert "go ahead" in body
    assert "merge on forge" not in body.lower()
    assert forbidden_buzz_hits(body) == []


@pytest.mark.asyncio
async def test_land_calls_land_pull_request() -> None:
    poster = _FakePoster()
    forge = MagicMock()
    forge.land_pull_request = AsyncMock(
        return_value=ForgeActionResult(
            action="land_pull_request",
            repo="demo-meta",
            pr_number=9,
            url="sha-landed",
        )
    )
    workspace = MagicMock()
    workspace.pm_app_role.return_value = MagicMock()
    workspace.sync_integration_branch.return_value = {
        "branch": "develop",
        "sha": "abc",
        "mode": "ff_only",
    }
    workspace.purge_local_paths.return_value = []

    prog = object.__new__(KbEnrichProgramme)
    prog.role_id = "adh.kb"
    prog._poster = poster  # type: ignore[attr-defined]
    prog._briefs = HermesBriefService()  # type: ignore[attr-defined]
    prog._store = AsyncMock()  # type: ignore[attr-defined]
    prog._forge = forge  # type: ignore[attr-defined]
    prog._workspace = workspace  # type: ignore[attr-defined]

    tenant = TenantContext(
        slug="demo",
        org="org",
        meta_repo="demo-meta",
        meta_root="/tmp/demo-meta",
        ops_room="demo-ops",
        integration_branch="develop",
        init_prefix="INIT-",
    )
    session = AgentWorkSession(
        tenant_slug="demo",
        role_id="adh.kb",
        room="demo-ops",
        work_id="KB-INIT-1",
        initiative="INIT-1",
        programme="kb-enrich",
        stage="kb-enrich-land",
        awaiting=AWAITING_JUDGMENT,
        slots={"enrich_pr": "https://github.com/org/demo-meta/pull/9", "enrich_pr_number": "9"},
    )
    await prog._land_enrich_pr(tenant, "demo-ops", session)  # type: ignore[attr-defined]
    forge.land_pull_request.assert_awaited_once()
    workspace.sync_integration_branch.assert_called_once()
    assert session.stage == "kb-enrich-landed"
    assert any("Landed knowledge docs" in p[0] for p in poster.posts)
