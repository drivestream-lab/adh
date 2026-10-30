"""Lead outline on Buzz: ack, think C1/C2, quality, reject duplicate."""

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.business_services.hermes_service import (
    HermesService,
    _coerce_init,
    _lock_token,
    apply_ready_gate,
    apply_recommend_gate,
    outline_fingerprint,
    parse_ask_answers,
    parse_promote_pick,
)
from src.infra_services.pm_workspace_service import MetaInventory, think_path
from src.models.prompt_models import cap_ask_forks
from src.infra_services.prompt_service import PromptService
from src.models.buzz_models import EventType, MessageKind, MessageRead
from src.models.hermes_models import HermesArtifactRead
from src.models.tenant_models import TenantContext


_OUTLINE = (
    "Home is empty. I want a visitor to see that, then after someone registers "
    "and publishes one article, that article should show on home and open. "
    "API and web. Not comments, follow, or favorites. Propose the INIT and the PRD candidate."
)

_INIT = "INIT-REALWORLD-001"
_OPS = "realworld-ops"

_TENANT = TenantContext(
    slug="realworld",
    org="drivestream-lab",
    meta_repo="realworld-meta",
    meta_root="/tmp/realworld-meta",
    integration_branch="develop",
    repos={
        "realworld-meta": "meta-pm",
        "realworld-api": "python-backend",
        "realworld-web": "nextjs-frontend",
        "realworld-local": "compose-local",
    },
)


def _message(
    body: str,
    *,
    handle: str = "nikd10x",
    kind: MessageKind = MessageKind.MESSAGE,
) -> MessageRead:
    return MessageRead(
        id=uuid4(),
        room_id=uuid4(),
        identity_id=uuid4(),
        identity_handle=handle,
        identity_display_name=handle,
        body=body,
        kind=kind,
    )


def _think_artifact(label: str = "C1") -> HermesArtifactRead:
    run = int(label[1:]) if len(label) > 1 and label[1:].isdigit() else 1
    path = think_path(_INIT, run)
    job = "Visitor sees empty home, then one published article."
    return HermesArtifactRead(
        id=uuid4(),
        kind=f"pm_think_{label.lower()}",
        initiative=_INIT,
        rubric_id="rubric-pm",
        body=f"Think {label}  {_INIT}",
        payload={
            "lane": "pm",
            "hop": f"think-{label.lower()}",
            "model": "qwen",
            "path": path,
            "file_body": f"# {_INIT}\n\n- **Job:** {job}\n",
            "artifact": {
                "proposed_init": _INIT,
                "candidate_label": label,
                "job": job,
                "summary": "Empty home then one article.",
            },
        },
    )


def _ask_artifact() -> HermesArtifactRead:
    return HermesArtifactRead(
        id=uuid4(),
        kind="pm_ask",
        initiative=_INIT,
        rubric_id="rubric-pm",
        body=f"Ask  {_INIT}",
        payload={
            "lane": "pm",
            "hop": "ask",
            "path": f"prd/reports/{_INIT}-prd-ask.md",
            "file_body": f"# {_INIT}-prd-ask\n",
            "artifact": {
                "forks": [
                    {
                        "id": "F1",
                        "question": "If two people publish, does home show both?",
                        "choices": [
                            "all published, newest first, no pagination",
                            "only proving one article",
                        ],
                        "why_it_changes_the_pick": "C1 leaves this open; C2 locks all-on-home.",
                        "quote": "OQ-03",
                    }
                ],
                "notes": "",
            },
        },
    )


def _recommend_artifact() -> HermesArtifactRead:
    return HermesArtifactRead(
        id=uuid4(),
        kind="pm_recommend",
        initiative=_INIT,
        rubric_id="rubric-pm",
        body=f"Recommend  {_INIT}",
        payload={
            "lane": "pm",
            "hop": "recommend",
            "path": f"prd/reports/{_INIT}-prd-recommend.md",
            "file_body": f"# {_INIT}-prd-recommend\n",
            "artifact": {
                "recommend": "C1",
                "path": think_path(_INIT, 1),
                "why": "Closest to the empty-home then one-article brief.",
                "why_not": [{"label": "C2", "why_not": "Added unpublish."}],
                "residual_locks": ["multi-article home"],
                "engineering_ready": "no",
                "notes": "",
            },
        },
    )


def _quality_artifact(*, handover_c2: str = "yes") -> HermesArtifactRead:
    return HermesArtifactRead(
        id=uuid4(),
        kind="pm_quality",
        initiative=_INIT,
        rubric_id="rubric-pm",
        overall=2.1,
        body=f"Quality  {_INIT}",
        payload={
            "lane": "pm",
            "hop": "quality",
            "model": "qwen",
            "pass_number": 1,
            "max_passes": 2,
            "path": f"prd/reports/{_INIT}-prd-quality.md",
            "file_body": f"# {_INIT}-prd-quality\n",
            "artifact": {
                "rank": "C2-wins",
                "recommend_promote": "C2" if handover_c2 == "yes" else "",
                "candidates": [
                    {
                        "label": "C1",
                        "path": think_path(_INIT, 1),
                        "handover": "no",
                        "material_fails": ["B1 Job is empty"],
                        "bars": [
                            {
                                "bar": "B1",
                                "result": "FAIL",
                                "material": True,
                                "evidence": "Job empty",
                            }
                        ],
                        "overall": 1.8,
                    },
                    {
                        "label": "C2",
                        "path": think_path(_INIT, 2),
                        "handover": handover_c2,
                        "material_fails": [] if handover_c2 == "yes" else ["B3 missing observable"],
                        "bars": [
                            {
                                "bar": "B1",
                                "result": "PASS",
                                "material": True,
                                "evidence": "Job quote",
                            }
                        ],
                        "overall": 2.1,
                    },
                ],
            },
        },
    )


def _registry(*tenants: TenantContext) -> MagicMock:
    live = list(tenants) or [_TENANT]
    registry = MagicMock()
    registry.active.return_value = live
    registry.by_ops_room.side_effect = lambda room: next(
        (tenant for tenant in live if tenant.ops_room == room), None
    )
    return registry


def _service(
    *tenants: TenantContext,
) -> tuple[HermesService, MagicMock, MagicMock, AsyncMock, AsyncMock]:
    buzz = MagicMock()
    buzz.post_message = AsyncMock(side_effect=lambda _room, payload: payload)
    buzz.ingest_heartbeat = AsyncMock()
    redis = MagicMock()
    redis.set_if_absent = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    workspace = MagicMock()
    workspace.publish = AsyncMock(
        return_value={"local_path": "/tmp/prd/reports/x.md", "github": {"commit_sha": "abc1234"}}
    )
    workspace.inventory = MagicMock(return_value=MetaInventory())
    workspace.read_local = MagicMock(return_value="")
    redis.set = AsyncMock(return_value=True)
    prompts = PromptService(MagicMock())
    asyncio.run(prompts.initialize())
    hermes = HermesService(MagicMock(), buzz, redis, prompts, workspace, _registry(*tenants))
    hermes._settings = hermes._settings.model_copy(update={"pm_ask_wait_seconds": 0})

    async def _think_side_effect(request: object, **kwargs: object) -> HermesArtifactRead:
        run_raw = kwargs.get("run", 1)
        run = run_raw if isinstance(run_raw, int) else 1
        artifact = _think_artifact(f"C{run}")
        initiative = str(getattr(request, "initiative", None) or _INIT)
        path = str(kwargs.get("path") or think_path(initiative, run))
        payload = dict(artifact.payload)
        parsed = dict(payload.get("artifact") or {})
        parsed["proposed_init"] = initiative
        payload["path"] = path
        payload["artifact"] = parsed
        return artifact.model_copy(update={"initiative": initiative, "payload": payload})

    think = AsyncMock(side_effect=_think_side_effect)
    quality = AsyncMock(return_value=_quality_artifact())
    hermes.run_pm_think = think
    hermes.run_pm_quality = quality
    hermes.run_pm_ask = AsyncMock(return_value=_ask_artifact())
    hermes.run_pm_recommend = AsyncMock(return_value=_recommend_artifact())
    return hermes, buzz, redis, think, quality


def test_outline_fingerprint_normalizes_whitespace() -> None:
    assert outline_fingerprint("Home   is empty") == outline_fingerprint("home is empty")


def test_coerce_init_uses_programme_slug() -> None:
    assert _coerce_init("INIT-REALWORLD-HOME-PUBLISH-001", "realworld") == (
        "INIT-REALWORLD-HOME-PUBLISH-001"
    )
    assert _coerce_init("INIT-ADH-HOME-PUBLISH-001", "realworld") == (
        "INIT-REALWORLD-HOME-PUBLISH-001"
    )
    assert _coerce_init("INIT-RW-HOME", "realworld") == "INIT-REALWORLD-HOME"
    assert _coerce_init("not-an-id", "realworld") == "INIT-REALWORLD-PENDING"


def test_empty_meta_allocates_next_numbered_init() -> None:
    hermes, buzz, redis, think, quality = _service()
    cast(MagicMock, hermes._workspace).inventory.return_value = MetaInventory()

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks)

    asyncio.run(_run())
    bodies = [call.args[1].body for call in buzz.post_message.await_args_list]
    assert any("Received your outline" in body for body in bodies)
    assert any("allocated INIT-REALWORLD-001" in body for body in bodies)
    assert not any("cannot allocate INIT" in body for body in bodies)
    assert any("Calling the model for think C1" in body for body in bodies)
    assert think.await_count == 2
    assert think.await_args_list[0].args[0].initiative == _INIT
    assert think.await_args_list[0].kwargs["path"] == f"prd/reports/{_INIT}-prd-think.md"
    assert think.await_args_list[1].kwargs["path"] == f"prd/reports/{_INIT}-prd-think-2.md"
    assert quality.await_count == 1
    redis.delete.assert_awaited()


def test_occupied_numbered_init_allocates_next() -> None:
    hermes, buzz, redis, think, quality = _service()
    cast(MagicMock, hermes._workspace).inventory.return_value = MetaInventory(
        inits=[_INIT],
        think_paths=[f"prd/reports/{_INIT}-prd-think.md"],
    )

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks)

    asyncio.run(_run())
    posts = [call.args[1] for call in buzz.post_message.await_args_list]
    bodies = [post.body for post in posts]
    assert any("allocated INIT-REALWORLD-002" in body for body in bodies)
    assert any("Calling the model for think C1" in body for body in bodies)
    assert any("Calling the model for think C2" in body for body in bodies)
    assert any("Calling the model for quality" in body for body in bodies)
    assert any(post.kind == MessageKind.MESSAGE and "Think C1" in post.body for post in posts)
    assert any("Promote is still you" in body for body in bodies)
    assert think.await_count == 2
    assert think.await_args_list[0].kwargs["path"] == "prd/reports/INIT-REALWORLD-002-prd-think.md"
    assert (
        think.await_args_list[1].kwargs["path"] == "prd/reports/INIT-REALWORLD-002-prd-think-2.md"
    )
    assert quality.await_count == 1
    redis.delete.assert_awaited()


def test_job_shaped_occupied_init_does_not_become_the_id() -> None:
    hermes, _buzz, _redis, think, _quality = _service()
    cast(MagicMock, hermes._workspace).inventory.return_value = MetaInventory(
        inits=["INIT-REALWORLD-HOME-PUBLISH-001"],
        think_paths=[],
    )

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks)

    asyncio.run(_run())
    assert think.await_count == 2
    assert think.await_args_list[0].args[0].initiative == _INIT


def test_catch_up_resumes_pending_outline_with_allocated_init() -> None:
    hermes, _buzz, _redis, think, quality = _service()
    hermes._awaiting_init["realworld"] = {
        "outline": _OUTLINE,
        "fingerprint": outline_fingerprint(_OUTLINE),
        "source_id": str(uuid4()),
        "room": _OPS,
    }

    async def _run() -> None:
        await hermes._resume_pending_outline(_TENANT)

    asyncio.run(_run())
    assert think.await_count == 2
    assert think.await_args_list[0].args[0].initiative == _INIT
    assert quality.await_count == 1


def test_job_shaped_lead_init_is_ignored() -> None:
    hermes, buzz, _redis, think, quality = _service()

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message("INIT-REALWORLD-EMPTY-HOME-PUBLISHING"))

    asyncio.run(_run())
    think.assert_not_awaited()
    quality.assert_not_awaited()
    buzz.post_message.assert_not_awaited()


def test_lead_names_numbered_init_resumes_pending() -> None:
    hermes, _buzz, _redis, think, quality = _service()
    cast(MagicMock, hermes._workspace).inventory.return_value = MetaInventory(
        inits=[_INIT], think_paths=[]
    )
    fingerprint = outline_fingerprint(_OUTLINE)
    hermes._awaiting_init["realworld"] = {
        "outline": _OUTLINE,
        "fingerprint": fingerprint,
        "source_id": str(uuid4()),
        "room": _OPS,
    }

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_INIT))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks)

    asyncio.run(_run())
    assert think.await_count == 2
    assert think.await_args_list[0].args[0].initiative == _INIT
    assert quality.await_count == 1


def test_duplicate_while_in_progress_is_rejected() -> None:
    hermes, buzz, _redis, think, quality = _service()
    fingerprint = outline_fingerprint(_OUTLINE)
    hermes._inflight[_lock_token("realworld", fingerprint)] = str(uuid4())

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))

    asyncio.run(_run())
    bodies = [call.args[1].body for call in buzz.post_message.await_args_list]
    assert any("already in progress" in body for body in bodies)
    events = [call.args[1].event_type for call in buzz.post_message.await_args_list]
    assert EventType.STALL in events
    think.assert_not_awaited()
    quality.assert_not_awaited()


def test_duplicate_is_rejected_while_work_still_runs() -> None:
    hermes, buzz, _redis, think, quality = _service()
    started = asyncio.Event()
    resume = asyncio.Event()

    async def _slow(*_args: object, **kwargs: object) -> HermesArtifactRead:
        run_raw = kwargs.get("run", 1)
        run = run_raw if isinstance(run_raw, int) else 1
        if run <= 1:
            started.set()
            await resume.wait()
            return _think_artifact("C1")
        return _think_artifact("C2")

    think.side_effect = _slow
    hermes._settings = hermes._settings.model_copy(
        update={"wait_step_seconds": 0.05, "wait_steps": 20, "progress_seconds": 0.05}
    )

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))
        await started.wait()
        await asyncio.sleep(0.12)
        await hermes.on_room_message(_OPS, _message(_OUTLINE))
        resume.set()
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks)

    asyncio.run(_run())
    bodies = [call.args[1].body for call in buzz.post_message.await_args_list]
    assert any("already in progress" in body for body in bodies)
    assert any("Still working" in body for body in bodies)
    assert think.await_count == 2
    assert quality.await_count == 1


def test_fails_after_wait_steps_without_stub_prd() -> None:
    hermes, buzz, redis, think, quality = _service()

    async def _hang(*_args: object, **_kwargs: object) -> HermesArtifactRead:
        await asyncio.sleep(10)
        return _think_artifact("C1")

    think.side_effect = _hang
    hermes._settings = hermes._settings.model_copy(
        update={"wait_step_seconds": 0.05, "wait_steps": 3, "progress_seconds": 0.05}
    )

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks)

    asyncio.run(_run())
    posts = [call.args[1] for call in buzz.post_message.await_args_list]
    bodies = [post.body for post in posts]
    assert any("1/3" in body for body in bodies)
    assert any("Failed:" in body and "3 waits" in body for body in bodies)
    assert EventType.STALL in [post.event_type for post in posts]
    assert not any(post.kind == MessageKind.MESSAGE and "Think C1" in post.body for post in posts)
    assert not any(
        post.kind == MessageKind.MESSAGE and "PRD candidate" in post.body for post in posts
    )
    quality.assert_not_awaited()
    cast(MagicMock, hermes._workspace).publish.assert_not_awaited()
    redis.delete.assert_awaited()


def test_stub_model_is_not_posted_as_prd() -> None:
    hermes, buzz, _redis, think, quality = _service()
    think.side_effect = [
        _think_artifact("C1").model_copy(
            update={"payload": {"lane": "pm", "model": "stub", "stub": True, "artifact": {}}}
        )
    ]

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks)

    asyncio.run(_run())
    posts = [call.args[1] for call in buzz.post_message.await_args_list]
    assert any("fake hop" in post.body for post in posts)
    assert EventType.STALL in [post.event_type for post in posts]
    assert not any(post.kind == MessageKind.MESSAGE and "Think C1" in post.body for post in posts)
    assert not any(
        post.kind == MessageKind.MESSAGE and "PRD candidate" in post.body for post in posts
    )
    quality.assert_not_awaited()
    cast(MagicMock, hermes._workspace).publish.assert_not_awaited()


def test_format_think_hop_is_logical_output() -> None:
    hermes, *_rest = _service()
    body = hermes._render_think_hop(_think_artifact("C1"))
    assert body.startswith(f"Think C1  {_INIT}")
    assert "Job:" in body
    assert "prd/reports/" in body
    assert "Hermes will not merge" in body


def test_ignores_agents_and_short_chatter() -> None:
    hermes, buzz, _redis, think, quality = _service()

    async def _run() -> None:
        await hermes.on_room_message(
            _OPS,
            _message("please start the PM lane now", handle="adh.orchestrator"),
        )
        await hermes.on_room_message(_OPS, _message("ok"))

    asyncio.run(_run())
    buzz.post_message.assert_not_awaited()
    think.assert_not_awaited()
    quality.assert_not_awaited()


def test_lead_stop_halts_inflight_think() -> None:
    hermes, buzz, _redis, think, quality = _service()
    started = asyncio.Event()

    async def _hang(*_a: object, **_k: object) -> HermesArtifactRead:
        started.set()
        await asyncio.Event().wait()
        return _think_artifact("C1")

    think.side_effect = _hang

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))
        await asyncio.wait_for(started.wait(), timeout=2)
        await hermes.on_room_message(_OPS, _message("stop"))
        if hermes._work_tasks:
            await asyncio.gather(*list(hermes._work_tasks), return_exceptions=True)

    asyncio.run(_run())
    bodies = [call.args[1].body for call in buzz.post_message.await_args_list]
    assert any("Stopped" in body and "Lead `stop`" in body for body in bodies)
    quality.assert_not_awaited()
    assert think.await_count == 1


def test_factory_ops_outline_is_ignored() -> None:
    hermes, buzz, _redis, think, quality = _service()

    async def _run() -> None:
        await hermes.on_room_message("adh-ops", _message(_OUTLINE))

    asyncio.run(_run())
    buzz.post_message.assert_not_awaited()
    think.assert_not_awaited()
    quality.assert_not_awaited()


def test_two_tenants_can_claim_the_same_outline() -> None:
    other = TenantContext(
        slug="acme",
        org="drivestream-lab",
        meta_repo="acme-meta",
        meta_root="/tmp/acme-meta",
        integration_branch="develop",
        repos={"acme-meta": "meta-pm"},
    )
    hermes, _buzz, redis, think, _quality = _service(_TENANT, other)
    think.side_effect = [
        _think_artifact("C1"),
        _think_artifact("C2"),
        _think_artifact("C1"),
        _think_artifact("C2"),
    ]

    async def _run() -> None:
        await hermes.on_room_message("realworld-ops", _message(_OUTLINE))
        await hermes.on_room_message("acme-ops", _message(_OUTLINE))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks)

    asyncio.run(_run())
    assert redis.set_if_absent.await_count == 2
    keys = [call.args[0] for call in redis.set_if_absent.await_args_list]
    assert any(key.startswith("adh:pm:inflight:realworld:") for key in keys)
    assert any(key.startswith("adh:pm:inflight:acme:") for key in keys)


def test_quality_scores_think_files_not_skill_json() -> None:
    hermes, _buzz, _redis, _think, quality = _service()

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks)

    asyncio.run(_run())
    called = quality.await_args
    assert called is not None
    files = called.kwargs["files"]
    assert [item["label"] for item in files] == ["C1", "C2"]
    assert files[0]["path"] == think_path(_INIT, 1)
    assert "**Job:**" in files[0]["file_body"]
    assert called.kwargs["pass_number"] == 1
    assert "candidate_c1" not in called.kwargs


def test_no_handover_writes_c3_c4_then_stops() -> None:
    hermes, buzz, _redis, think, quality = _service()
    quality.side_effect = [
        _quality_artifact(handover_c2="no"),
        _quality_artifact(handover_c2="no"),
    ]

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks)

    asyncio.run(_run())
    bodies = [call.args[1].body for call in buzz.post_message.await_args_list]
    assert think.await_count == 4
    assert think.await_args_list[2].kwargs["run"] == 3
    assert think.await_args_list[3].kwargs["path"] == think_path(_INIT, 4)
    assert quality.await_count == 2
    assert any("Loop continues to /prd-think C3" in body for body in bodies)
    assert any("Ready loop stop (max-ready)" in body for body in bodies)
    assert any("Promote is still you" in body for body in bodies)


def test_skeleton_gate_blocks_handover_yes() -> None:
    parsed = apply_ready_gate(
        {
            "candidates": [
                {
                    "label": "C1",
                    "path": "prd/reports/x.md",
                    "handover": "yes",
                    "bars": [],
                    "scores": {},
                }
            ],
            "recommend_promote": "C1",
        },
        [
            {
                "label": "C1",
                "path": "prd/reports/x.md",
                "file_body": (
                    "- **Job:** (none)\n- CAP-01:  (J: J-01)\n"
                    "- REQ-01: x → n/a\n- J-01: Visitor / ? → ?\n"
                ),
            }
        ],
    )
    cand = parsed["candidates"][0]
    assert cand["handover"] == "no"
    assert parsed["recommend_promote"] == ""
    assert any("B1" in item for item in cand["material_fails"])
    assert cand["bars"]


def test_after_quality_runs_ask_then_recommend() -> None:
    hermes, buzz, _redis, _think, quality = _service()

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks)

    asyncio.run(_run())
    bodies = [call.args[1].body for call in buzz.post_message.await_args_list]
    payloads = [call.args[1].payload or {} for call in buzz.post_message.await_args_list]
    assert quality.await_count == 1
    assert cast(AsyncMock, hermes.run_pm_ask).await_count == 1
    assert cast(AsyncMock, hermes.run_pm_recommend).await_count == 1
    assert any("Next hop: /prd-ask" in body for body in bodies)
    assert any("Next hop: /prd-recommend" in body for body in bodies)
    assert any(payload.get("status") == "need_ask" for payload in payloads)
    assert any(payload.get("choices") for payload in payloads if payload.get("hop") == "ask")
    assert any("Promote is still you" in body for body in bodies)


def test_chatter_during_ask_is_ignored() -> None:
    hermes, buzz, _redis, think, _quality = _service()
    hermes._settings = hermes._settings.model_copy(update={"pm_ask_wait_seconds": 2})
    chatter = (
        "please proceed with the highest score file and also add comments "
        "and favorites while you are at it so we can ship faster"
    )

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))
        for _ in range(80):
            bodies = [call.args[1].body for call in buzz.post_message.await_args_list]
            if any("Forks for" in body for body in bodies):
                break
            await asyncio.sleep(0.05)
        await hermes.on_room_message(_OPS, _message(chatter))
        await hermes.on_room_message(
            _OPS,
            _message(
                "F1: all published, newest first, no pagination\n" "F2: write=publish\n" "F3: skip"
            ),
        )
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks)

    asyncio.run(_run())
    assert think.await_count == 2
    assert cast(AsyncMock, hermes.run_pm_recommend).await_count == 1
    called = cast(AsyncMock, hermes.run_pm_recommend).await_args
    assert called is not None
    assert "all published" in called.kwargs["answers"]
    bodies = [call.args[1].body for call in buzz.post_message.await_args_list]
    assert not any("Received your outline" in body for body in bodies[1:] if "already" in body)
    assert not any("allocated INIT-REALWORLD-002" in body for body in bodies)


def test_ask_forks_capped_at_three() -> None:
    forks = cap_ask_forks(
        [
            {
                "question": "Multi-article home?",
                "choices": ["all published", "one article"],
                "why_it_changes_the_pick": "C1 vs C2",
            },
            {
                "question": "Write equals publish?",
                "choices": ["yes", "draft then publish"],
                "why": "C2 adds draft",
            },
            {
                "question": "Unpublish in scope?",
                "choices": ["no", "yes"],
                "why_it_changes_the_pick": "C2/C4 added it",
            },
            {
                "question": "Should we add comments?",
                "choices": ["no", "yes"],
                "why_it_changes_the_pick": "would create C5",
            },
            {"question": "Open essay?", "choices": ["tell me more"], "why": "open"},
        ],
        max_forks=3,
    )
    assert [item["id"] for item in forks] == ["F1", "F2", "F3"]
    assert all(len(item["choices"]) >= 2 for item in forks)


def test_recommend_gate_forces_none_and_not_ready() -> None:
    quality = _quality_artifact(handover_c2="no")
    files = [
        {"label": "C1", "path": think_path(_INIT, 1), "file_body": "c1"},
        {"label": "C2", "path": think_path(_INIT, 2), "file_body": "c2"},
    ]
    parsed = apply_recommend_gate(
        {
            "recommend": "C2",
            "path": think_path(_INIT, 2),
            "engineering_ready": "yes",
            "why": "highest score",
        },
        files,
        quality,
    )
    assert parsed["recommend"] == "C2"
    assert parsed["engineering_ready"] == "no"
    missing = apply_recommend_gate({"recommend": "C9", "engineering_ready": "yes"}, files, quality)
    assert missing["recommend"] == "none"
    assert missing["engineering_ready"] == "no"


def test_parse_ask_answers_and_promote_pick() -> None:
    assert parse_ask_answers("skip") == {"_skip": "skip"}
    assert parse_ask_answers("F1: all published\nF2: write=publish") == {
        "F1": "all published",
        "F2": "write=publish",
    }
    assert parse_ask_answers("okay proceed with C2") is None
    assert parse_promote_pick("C1") == "C1"
    assert parse_promote_pick("none") == "none"
    assert parse_promote_pick("please merge it") is None
