"""Lead listener: collaborator + skill authoring routing (LiteLLM authoring retired)."""

from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.business_services.hermes.lead_tokens import (
    _coerce_init,
    ask_shaped_outline,
    is_lead_outline_body,
    outline_fingerprint,
    parse_ask_answers,
    parse_promote_pick,
    validate_ask_answers,
)
from src.business_services.hermes_service import HermesService
from src.infra_services.pm_workspace_service import MetaInventory, next_programme_init
from src.infra_services.prompt_service import PromptService
from src.models.buzz_models import MessageKind, MessageRead
from src.models.tenant_models import TenantContext

_INIT = "INIT-REALWORLD-001"
_OPS = "realworld-ops"
_OUTLINE = (
    "Home is empty for visitors. Authors need one clear publish path. "
    "Keep scope to the realworld product only."
)

_TENANT = TenantContext(
    slug="realworld",
    org="drivestream-lab",
    meta_repo="realworld-meta",
    meta_root="/tmp/realworld-meta",
    integration_branch="develop",
    repos={"realworld-meta": "meta-pm"},
)


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
    reg.active = MagicMock(return_value=list(tenants) or [_TENANT])
    return reg


def _service(*tenants: TenantContext) -> HermesService:
    buzz = MagicMock()
    buzz.post_message = AsyncMock(side_effect=lambda _room, payload: payload)
    buzz.ingest_heartbeat = AsyncMock()
    redis = MagicMock()
    redis.set_if_absent = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    redis.set = AsyncMock(return_value=True)
    workspace = MagicMock()
    workspace.inventory = MagicMock(return_value=MetaInventory())
    workspace.read_local = MagicMock(return_value="")
    workspace.publish = AsyncMock(return_value={"local_path": "/tmp/x", "github": {}})
    prompts = PromptService(MagicMock())
    asyncio.run(prompts.initialize())
    collaborator = MagicMock()
    collaborator.handle_lead_message = AsyncMock(return_value=False)
    collaborator.set_programme_runner = MagicMock()
    authoring = MagicMock()
    authoring.handle_lead_message = AsyncMock(return_value=False)
    authoring.start_outline = AsyncMock()
    return HermesService(
        MagicMock(),
        buzz,
        redis,
        prompts,
        workspace,
        _registry(*tenants),
        MagicMock(),
        collaborator,
        MagicMock(),
        authoring,
    )


def test_outline_fingerprint_normalizes_whitespace() -> None:
    assert outline_fingerprint("  a   b\n") == outline_fingerprint("a b")


def test_coerce_init_uses_programme_slug() -> None:
    assert _coerce_init("INIT-001", "realworld").startswith("INIT-REALWORLD-")


def test_empty_meta_allocates_next_numbered_init() -> None:
    assert next_programme_init("INIT-REALWORLD-", []) == "INIT-REALWORLD-001"


def test_ask_shaped_body_is_not_an_outline() -> None:
    body = "F1: keep empty home\nF2: one publish path"
    assert ask_shaped_outline(body)
    assert not is_lead_outline_body(body, min_chars=20)


def test_parse_ask_answers_and_promote_pick() -> None:
    assert parse_ask_answers("F1: keep it") == {"F1": "keep it"}
    assert parse_promote_pick("C2") == "C2"
    assert parse_promote_pick("skip") == "skip"


def test_validate_ask_answers_requires_frozen_labels() -> None:
    forks = [{"id": "F1", "choices": ["keep", "cut"]}]
    assert validate_ask_answers({"F1": "keep"}, forks) is None
    assert validate_ask_answers({"F1": "nope"}, forks) == "choice_mismatch"


def test_ignores_agents_and_short_chatter() -> None:
    hermes = _service()

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message("hi", handle="adh.pm"))
        await hermes.on_room_message(_OPS, _message("ok"))

    asyncio.run(_run())
    cast(MagicMock, hermes._authoring).start_outline.assert_not_awaited()


def test_outline_starts_authoring() -> None:
    hermes = _service()

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))

    asyncio.run(_run())
    cast(MagicMock, hermes._authoring).start_outline.assert_awaited()


def test_collaborator_wins_over_authoring() -> None:
    hermes = _service()
    hermes._collaborator.handle_lead_message = AsyncMock(return_value=True)

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(f"post-pm {_INIT}"))

    asyncio.run(_run())
    hermes._collaborator.handle_lead_message.assert_awaited()
    cast(MagicMock, hermes._authoring).start_outline.assert_not_awaited()


def test_authoring_handles_promote_before_new_outline() -> None:
    hermes = _service()
    hermes._authoring.handle_lead_message = AsyncMock(return_value=True)

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message("C2"))

    asyncio.run(_run())
    hermes._authoring.handle_lead_message.assert_awaited()
    cast(MagicMock, hermes._authoring).start_outline.assert_not_awaited()


def test_duplicate_while_in_progress_is_rejected() -> None:
    hermes = _service()
    fp = outline_fingerprint(_OUTLINE)
    hermes._inflight[f"realworld:{fp}"] = "prior"

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))

    asyncio.run(_run())
    cast(MagicMock, hermes._authoring).start_outline.assert_not_awaited()


def test_lead_stop_halts() -> None:
    hermes = _service()
    hermes._inflight["realworld:abc"] = "1"
    hermes._open_initiative["realworld"] = _INIT

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message("stop"))

    asyncio.run(_run())
    assert "realworld:abc" not in hermes._inflight


def test_two_tenants_can_claim_the_same_outline() -> None:
    other = TenantContext(
        slug="acme",
        org="drivestream-lab",
        meta_repo="acme-meta",
        meta_root="/tmp/acme-meta",
        integration_branch="develop",
        repos={"acme-meta": "meta-pm"},
    )
    hermes = _service(_TENANT, other)

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(_OUTLINE))
        await hermes.on_room_message(other.ops_room, _message(_OUTLINE))

    asyncio.run(_run())
    assert cast(MagicMock, hermes._authoring).start_outline.await_count == 2
