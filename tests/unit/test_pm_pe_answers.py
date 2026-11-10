"""PM pe_answers — no human ack gate; emits pe.pm_answers."""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adh_agents.baton.models import Baton
from src.adh_agents.programmes.pm.pe_answers import PmPeAnswersProgramme, pm_pe_answers_path
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext


class _FakePoster:
    def __init__(self) -> None:
        self.posts: list[str] = []

    async def post_status(
        self,
        room: str,
        body: str,
        event_type: EventType = EventType.PROGRESS,
        payload: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        del room, event_type, payload, kwargs
        self.posts.append(body)


@pytest.mark.asyncio
async def test_answer_writes_artefact_and_emits_baton(tmp_path) -> None:  # noqa: ANN001
    meta = tmp_path / "meta"
    meta.mkdir()
    (meta / "prd" / "reports").mkdir(parents=True)
    questions = meta / "prd" / "reports" / "PE-Qs.md"
    questions.write_text("# Q\n\n- PQ-01 scope?\n", encoding="utf-8")

    workspace = MagicMock()
    workspace.read_local.side_effect = lambda _t, rel: (
        questions.read_text(encoding="utf-8") if "PE-Qs" in rel else ""
    )
    workspace.write_local = MagicMock()
    workspace.pm_app_role.return_value = MagicMock()

    batons = MagicMock()
    stored = MagicMock()
    stored.id = "b1"
    stored.correlation_id = "c1"
    stored.idempotency_key = "k1"
    batons.create_pending = AsyncMock(return_value=(stored, True))

    litellm = MagicMock()
    litellm.initialize = AsyncMock()
    litellm.complete = AsyncMock(return_value="### PQ-01\nKeep in scope.\n")

    forge = MagicMock()
    forge.comment_pr = AsyncMock(return_value=MagicMock(url="https://example/comment"))

    poster = _FakePoster()
    prog = object.__new__(PmPeAnswersProgramme)
    prog.role_id = "adh.pm"
    prog._batons = batons  # type: ignore[attr-defined]
    prog._poster = poster  # type: ignore[attr-defined]
    prog._workspace = workspace  # type: ignore[attr-defined]
    prog._forge = forge  # type: ignore[attr-defined]
    prog._litellm = litellm  # type: ignore[attr-defined]
    prog._settings = MagicMock(baton_ttl_seconds=3600)  # type: ignore[attr-defined]
    prog.logger = MagicMock()  # type: ignore[attr-defined]

    tenant = TenantContext(
        slug="demo",
        org="org",
        meta_repo="demo-meta",
        meta_root=str(meta),
        ops_room="demo-ops",
        integration_branch="develop",
        init_prefix="INIT-",
        repos={"api": "python"},
    )
    baton = Baton(
        type="pm.pe_questions",
        from_role="adh.pe",
        to_role="adh.pm",
        tenant="demo",
        ops_room="demo-ops",
        initiative="INIT-1",
        idempotency_key="pm.pe_questions:demo:INIT-1:r1",
        payload={
            "questions_path": "prd/reports/PE-Qs.md",
            "pr_url": "https://github.com/org/demo-meta/pull/3",
            "round": "1",
            "count": "1",
        },
    )
    path = await prog.answer_pe_questions(tenant, "demo-ops", baton)
    assert path == pm_pe_answers_path("INIT-1")
    workspace.write_local.assert_called()
    batons.create_pending.assert_awaited()
    emitted = batons.create_pending.await_args.args[0]
    assert emitted.type == "pe.pm_answers"
    assert not any("ack_pe" in p.lower() for p in poster.posts)
