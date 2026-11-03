"""Post-promote PM lane: gate, clean, VF briefs, manifest, impact."""

from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.business_services.hermes.decision_cards import apply_validate_briefs
from src.business_services.hermes.lead_tokens import (
    parse_finding_answers,
    parse_impact_answer,
    parse_manifest_answer,
    parse_post_promote_gate,
    promote_pick_wants_clean,
)
from src.business_services.hermes.promote_cleanup import (
    archive_dest,
    is_prepromote_scratch,
    scratch_paths_for_initiative,
)
from src.business_services.hermes.validation_report import (
    format_resolution_markdown,
    open_critical,
    parse_validation_findings,
)
from src.business_services.hermes_service import HermesService
from src.infra_services.pm_workspace_service import MetaInventory, prd_path, think_path
from src.infra_services.prompt_service import PromptService
from src.models.buzz_models import MessageKind, MessageRead
from src.models.tenant_models import TenantContext

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

_VALIDATION = """# Validation-Report-INIT-REALWORLD-001

## Critical
- VF-01 Scope gap on empty home
- VF-02 Auth edge case

## Should Fix
- VF-03 Naming inconsistency

## Verify
- VF-04 Analytics optional
"""


def _message(body: str, *, handle: str = "nikd10x") -> MessageRead:
    return MessageRead(
        id=uuid4(),
        room_id=uuid4(),
        identity_id=uuid4(),
        identity_handle=handle,
        identity_display_name=handle,
        body=body,
        kind=MessageKind.MESSAGE,
    )


def _registry(*tenants: TenantContext) -> MagicMock:
    reg = MagicMock()
    by_room = {t.ops_room: t for t in tenants} or {_OPS: _TENANT}
    by_slug = {t.slug: t for t in tenants} or {"realworld": _TENANT}
    reg.by_ops_room = MagicMock(side_effect=lambda room: by_room.get(room))
    reg.get = MagicMock(side_effect=lambda slug: by_slug.get(slug))
    return reg


def _service() -> tuple[HermesService, MagicMock, MagicMock, MagicMock]:
    buzz = MagicMock()
    buzz.post_message = AsyncMock(side_effect=lambda _room, payload: payload)
    buzz.ingest_heartbeat = AsyncMock()
    redis = MagicMock()
    redis.set_if_absent = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    redis.set = AsyncMock(return_value=True)
    workspace = MagicMock()
    workspace.publish = AsyncMock(
        return_value={"local_path": "/tmp/x.md", "github": {"commit_sha": "abc1234"}}
    )
    workspace.inventory = MagicMock(
        return_value=MetaInventory(
            inits=[_INIT],
            think_paths=[think_path(_INIT, 1), think_path(_INIT, 2)],
            prd_paths=[prd_path(_INIT)],
        )
    )
    workspace.read_local = MagicMock(return_value="")
    workspace.archive_paths = AsyncMock(
        return_value={
            "archived": [
                {
                    "source": think_path(_INIT, 1),
                    "dest": archive_dest(think_path(_INIT, 1), _INIT),
                }
            ],
            "skipped": [],
        }
    )
    prompts = PromptService(MagicMock())
    asyncio.run(prompts.initialize())
    skill_runner = MagicMock()
    skill_runner.run_skill = AsyncMock(
        return_value={"ok": True, "exit_code": 0, "output": "", "skill": "validate-requirements"}
    )
    hermes = HermesService(MagicMock(), buzz, redis, prompts, workspace, _registry(), skill_runner)
    hermes._settings = hermes._settings.model_copy(
        update={"pm_ask_wait_seconds": 0, "pm_max_validate_briefs": 2}
    )
    hermes._open_initiative["realworld"] = _INIT
    return hermes, buzz, workspace, skill_runner


def test_scratch_allowlist_never_includes_prd() -> None:
    paths = scratch_paths_for_initiative(
        _INIT,
        [
            prd_path(_INIT),
            think_path(_INIT, 1),
            f"prd/reports/{_INIT}-prd-quality.md",
            f"prd/reports/{_INIT}-prd-ask.md",
            f"prd/reports/Validation-Report-{_INIT}.md",
            f"prd/reports/{_INIT}-prd-think-9.md",
            "prd/reports/OTHER-prd-think.md",
        ],
    )
    assert prd_path(_INIT) not in paths
    assert f"prd/reports/Validation-Report-{_INIT}.md" not in paths
    assert think_path(_INIT, 1) in paths
    assert f"prd/reports/{_INIT}-prd-quality.md" in paths
    assert not is_prepromote_scratch(prd_path(_INIT), _INIT)


def test_parse_post_promote_and_finding_tokens() -> None:
    assert parse_post_promote_gate("validate") == "validate"
    assert parse_post_promote_gate("clean") == "clean"
    assert parse_post_promote_gate("retry validate") == "retry:validate"
    assert parse_post_promote_gate("coffee") is None
    pick, clean = promote_pick_wants_clean("C4|clean")
    assert pick == "C4" and clean is True
    answers = parse_finding_answers("VF-01: fix\nVF-02: defer")
    assert answers == {"VF-01": "fix", "VF-02": "defer"}
    assert parse_finding_answers("accept-recs") == {"_accept_recs": "1"}
    assert parse_finding_answers("explain VF-03") == {"VF-03": "explain"}
    assert parse_finding_answers("VF-01: fix VF-02: defer") == {"_invalid": "multi_vf_one_line"}
    assert parse_manifest_answer("apply") == {"_all": "apply"}
    assert parse_manifest_answer("CHG-01: hold") == {"CHG-01": "hold"}
    assert parse_impact_answer("confirm") == "confirm"


def test_parse_validation_findings_and_briefs() -> None:
    findings = parse_validation_findings(_VALIDATION)
    assert [row["id"] for row in findings] == ["VF-01", "VF-02", "VF-03", "VF-04"]
    assert len(open_critical(findings)) == 2
    briefs = apply_validate_briefs(
        findings[:2],
        {
            "briefs": [
                {
                    "id": "VF-01",
                    "question": "Should empty home be explicit?",
                    "example": "Visitor lands.",
                    "options": [{"choice": "fix", "means": "Add it"}],
                    "recommend": "fix",
                    "recommend_why": "Clarity",
                }
            ]
        },
    )
    assert briefs[0]["id"] == "VF-01"
    assert briefs[0]["question"] == "Should empty home be explicit?"
    assert briefs[0]["finding"]  # frozen
    assert briefs[1]["recommend"] == "fix"
    body = format_resolution_markdown(_INIT, {"VF-01": "fix", "VF-02": "reject"}, findings)
    assert "CHG-01" in body and "VF-01" in body and "Rejected" in body


def test_promote_awaits_validate_and_keeps_thinks() -> None:
    hermes, buzz, workspace, skill_runner = _service()
    source = think_path(_INIT, 2)
    workspace.inventory.return_value = MetaInventory(
        inits=[_INIT], think_paths=[think_path(_INIT, 1), source], prd_paths=[]
    )
    workspace.read_local.side_effect = lambda _t, path: ("THINK" if path == source else "")
    hermes._awaiting_recommend["realworld"] = {
        "room": _OPS,
        "initiative": _INIT,
        "recommend": "C2",
        "path": source,
        "think_paths": [think_path(_INIT, 1), source],
    }

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message("C2"))

    asyncio.run(_run())
    skill_runner.run_skill.assert_not_awaited()
    assert "realworld" in hermes._awaiting_post_promote
    publish_paths = [call.args[1] for call in workspace.publish.await_args_list]
    assert prd_path(_INIT) in publish_paths
    assert not any("prd/reports/_archive" in path for path in publish_paths)
    payloads = [call.args[1].payload or {} for call in buzz.post_message.await_args_list]
    assert any(p.get("status") == "awaiting_validate" for p in payloads)


def test_clean_archives_allowlist_only() -> None:
    hermes, buzz, workspace, _runner = _service()
    hermes._awaiting_post_promote["realworld"] = {
        "room": _OPS,
        "initiative": _INIT,
        "prd_path": prd_path(_INIT),
    }

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message("clean"))

    asyncio.run(_run())
    workspace.archive_paths.assert_awaited()
    moves = workspace.archive_paths.await_args.args[1]
    sources = [src for src, _dest in moves]
    assert think_path(_INIT, 1) in sources
    assert prd_path(_INIT) not in sources
    bodies = [call.args[1].body for call in buzz.post_message.await_args_list]
    assert any("Archived pre-promote scratch" in body for body in bodies)


def test_validate_batches_and_accept_recs() -> None:
    hermes, buzz, workspace, skill_runner = _service()
    hermes._awaiting_post_promote["realworld"] = {
        "room": _OPS,
        "initiative": _INIT,
        "prd_path": prd_path(_INIT),
    }

    def _read(_tenant: object, path: str) -> str:
        if "Validation-Report" in path:
            return _VALIDATION
        return "# impact\n"

    workspace.read_local.side_effect = _read
    prompts = cast(PromptService, hermes._prompts)
    prompts.complete = AsyncMock(  # type: ignore[method-assign]
        return_value=MagicMock(
            parsed={
                "briefs": [
                    {
                        "id": "VF-01",
                        "question": "Q1",
                        "example": "E1",
                        "options": [],
                        "recommend": "fix",
                        "recommend_why": "why",
                    },
                    {
                        "id": "VF-02",
                        "question": "Q2",
                        "example": "E2",
                        "options": [],
                        "recommend": "defer",
                        "recommend_why": "why2",
                    },
                ]
            }
        )
    )

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message("validate"))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks, return_exceptions=True)
        await hermes.on_room_message(_OPS, _message("accept-recs"))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks, return_exceptions=True)

    asyncio.run(_run())
    skill_runner.run_skill.assert_awaited()
    assert any(
        call.kwargs.get("skill_id") == "validate-requirements"
        or (call.args[1] if len(call.args) > 1 else None) == "validate-requirements"
        for call in skill_runner.run_skill.await_args_list
    )
    # first wave size capped at pm_max_validate_briefs=2
    pending = hermes._awaiting_validate_decisions.get("realworld")
    # after accept-recs of wave, either next wave pending or resolution published
    assert pending is not None or any(
        "Resolution" in str(call.args[1]) for call in workspace.publish.await_args_list
    )
    payloads = [call.args[1].payload or {} for call in buzz.post_message.await_args_list]
    assert any(p.get("status") == "need_validate_decisions" for p in payloads)


def test_explain_does_not_advance() -> None:
    hermes, buzz, _workspace, _runner = _service()
    hermes._awaiting_validate_decisions["realworld"] = {
        "room": _OPS,
        "initiative": _INIT,
        "findings": [{"id": "VF-01", "severity": "Critical", "finding": "x"}],
        "wave": [
            {
                "id": "VF-01",
                "severity": "Critical",
                "finding": "x",
                "question": "Q",
                "example": "E",
                "options": [{"choice": "fix", "means": "m"}],
                "recommend": "fix",
                "recommend_why": "w",
            }
        ],
        "decisions": {},
    }

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message("VF-01: explain"))

    asyncio.run(_run())
    assert hermes._awaiting_validate_decisions["realworld"]["decisions"] == {}
    payloads = [call.args[1].payload or {} for call in buzz.post_message.await_args_list]
    assert any(p.get("status") == "need_validate_decisions" for p in payloads)


def test_partial_answers_keep_pending() -> None:
    hermes, buzz, _workspace, _runner = _service()
    hermes._awaiting_validate_decisions["realworld"] = {
        "room": _OPS,
        "initiative": _INIT,
        "findings": [
            {"id": "VF-01", "severity": "Critical", "finding": "a"},
            {"id": "VF-02", "severity": "Critical", "finding": "b"},
        ],
        "wave": [
            {"id": "VF-01", "recommend": "fix", "question": "q1", "options": []},
            {"id": "VF-02", "recommend": "fix", "question": "q2", "options": []},
        ],
        "decisions": {},
    }

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message("VF-01: fix"))

    asyncio.run(_run())
    pending = hermes._awaiting_validate_decisions["realworld"]
    assert pending["decisions"] == {"VF-01": "fix"}
    bodies = [call.args[1].body for call in buzz.post_message.await_args_list]
    assert any("1/2" in body for body in bodies)


def test_zero_findings_skips_to_impact() -> None:
    hermes, buzz, workspace, skill_runner = _service()
    hermes._awaiting_post_promote["realworld"] = {
        "room": _OPS,
        "initiative": _INIT,
        "prd_path": prd_path(_INIT),
    }
    workspace.read_local.side_effect = lambda _t, path: (
        "# Validation empty\n" if "Validation" in path else "# Impact\nok\n"
    )

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message("validate"))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks, return_exceptions=True)

    asyncio.run(_run())
    skills = [
        call.args[1] if len(call.args) > 1 else call.kwargs.get("skill_id")
        for call in skill_runner.run_skill.await_args_list
    ]
    assert "validate-requirements" in skills
    assert "prd-impact-map" in skills
    payloads = [call.args[1].payload or {} for call in buzz.post_message.await_args_list]
    assert any(p.get("status") == "zero_findings" for p in payloads)
    assert any(p.get("status") == "need_impact_confirm" for p in payloads)


def test_impact_confirm_no_forge_and_stop_halts() -> None:
    hermes, buzz, _workspace, skill_runner = _service()
    hermes._awaiting_impact_confirm["realworld"] = {
        "room": _OPS,
        "initiative": _INIT,
    }

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message("confirm"))

    asyncio.run(_run())
    payloads = [call.args[1].payload or {} for call in buzz.post_message.await_args_list]
    assert any(p.get("status") == "forge_baton_ready" for p in payloads)
    # soft gate remains for clean
    assert "realworld" in hermes._awaiting_post_promote
    skill_runner.run_skill.assert_not_awaited()

    async def _stop() -> None:
        await hermes.on_room_message(_OPS, _message("stop"))

    asyncio.run(_stop())
    assert "realworld" not in hermes._awaiting_post_promote


def test_skill_failure_stalls_with_retry() -> None:
    hermes, buzz, workspace, skill_runner = _service()
    hermes._awaiting_post_promote["realworld"] = {
        "room": _OPS,
        "initiative": _INIT,
        "prd_path": prd_path(_INIT),
    }
    skill_runner.run_skill = AsyncMock(
        return_value={
            "ok": False,
            "exit_code": 2,
            "output": "boom",
            "skill": "validate-requirements",
        }
    )

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message("validate"))
        if hermes._work_tasks:
            await asyncio.gather(*hermes._work_tasks, return_exceptions=True)

    asyncio.run(_run())
    payloads = [call.args[1].payload or {} for call in buzz.post_message.await_args_list]
    assert any(p.get("status") == "skill_failed" for p in payloads)
    assert "realworld" in hermes._awaiting_post_promote
    bodies = [call.args[1].body for call in buzz.post_message.await_args_list]
    assert any("retry" in body.lower() for body in bodies)
