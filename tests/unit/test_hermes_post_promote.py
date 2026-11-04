"""Promote helpers + collaborator routing after authoring skill cutover."""

from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.business_services.hermes.decision_cards import apply_validate_briefs
from src.business_services.hermes.lead_tokens import promote_pick_wants_clean
from src.business_services.hermes.promote_cleanup import (
    archive_dest,
    is_prepromote_scratch,
    scratch_paths_for_initiative,
)
from src.business_services.hermes.runtime.orchestrator_service import match_reply_token
from src.business_services.hermes.programmes.meta_pm_programme import (
    post_pm_brief_from_hermes,
)
from src.business_services.hermes.validation_report import (
    format_resolution_markdown,
    open_critical,
    parse_validation_findings,
)
from src.business_services.hermes_service import HermesService
from src.infra_services.pm_workspace_service import (
    MetaInventory,
    hermes_post_pm_brief_path,
    prd_path,
    think_path,
)
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


def _registry() -> MagicMock:
    reg = MagicMock()
    reg.by_ops_room = MagicMock(return_value=_TENANT)
    reg.get = MagicMock(return_value=_TENANT)
    return reg


def _service() -> HermesService:
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
    workspace.read_local = MagicMock(return_value="THINK")
    workspace.archive_paths = AsyncMock(return_value={"archived": [], "skipped": []})
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
        _registry(),
        MagicMock(),
        collaborator,
        MagicMock(),
        authoring,
    )


def test_scratch_allowlist_never_includes_prd() -> None:
    paths = scratch_paths_for_initiative(
        _INIT,
        [
            prd_path(_INIT),
            think_path(_INIT, 1),
            f"prd/reports/{_INIT}-prd-quality.md",
            f"prd/reports/Validation-Report-{_INIT}.md",
        ],
    )
    assert prd_path(_INIT) not in paths
    assert think_path(_INIT, 1) in paths
    assert not is_prepromote_scratch(prd_path(_INIT), _INIT)
    assert archive_dest(think_path(_INIT, 1), _INIT).startswith("prd/reports/_archive/")


def test_brief_reply_tokens_not_global_allowlist() -> None:
    pick, clean = promote_pick_wants_clean("C4|clean")
    assert pick == "C4" and clean is True
    tokens = ["C1", "C2", "skip"]
    assert match_reply_token("C2", tokens) == "C2"
    assert match_reply_token("coffee", tokens) is None


def test_parse_validation_findings_and_briefs() -> None:
    findings = parse_validation_findings(_VALIDATION)
    assert [row["id"] for row in findings] == ["VF-01", "VF-02", "VF-03", "VF-04"]
    assert len(open_critical(findings)) == 2
    briefs = apply_validate_briefs(findings[:1], {"briefs": []})
    assert briefs[0]["id"] == "VF-01"
    body = format_resolution_markdown(_INIT, {"VF-01": "fix"}, findings)
    assert "VF-01" in body


_VALIDATION_TITLED = """# Requirements Review

## Critical (MUST FIX — factually wrong or misleading)

| VF | Type | Location | Target | Check | Finding | Source Says | Doc Claims | Example | Recommendation |
|----|------|----------|--------|-------|---------|-------------|------------|---------|----------------|
| VF-01 | Structural | Header | — | S1 | Promoted path still carries staging metadata | Promote brief | Title candidate | Misleading | Scrub staging framing |

## Should Fix (reframe, relocate, or make precise)

| VF | Type | Location | Target | Check | Finding | Recommendation |
|----|------|----------|--------|-------|---------|----------------|
| VF-02 | Semantic | §5 | CAP-03 | 11 | Journey list mismatch | Remove bad journeys |

## Verify (needs user confirmation)

| VF | Type | Location | Target | Check | Finding | Question for User |
|----|------|----------|--------|-------|---------|-------------------|
| — | — | — | — | — | None | — |

## Gaps (missing coverage)

| VF | Type | Location | Target | Check | Finding | Suggested Addition |
|----|------|----------|--------|-------|---------|---------------------|
| — | — | — | — | — | None | — |
"""


def test_parse_validation_findings_titled_sections_and_tables() -> None:
    findings = parse_validation_findings(_VALIDATION_TITLED)
    assert [row["id"] for row in findings] == ["VF-01", "VF-02"]
    assert findings[0]["severity"] == "Critical"
    assert "staging metadata" in findings[0]["finding"]
    assert findings[0]["location"] == "Header"
    assert "Scrub" in findings[0]["recommendation"]
    assert findings[1]["severity"] == "Should Fix"
    assert "Journey list" in findings[1]["finding"]
    assert len(open_critical(findings)) == 1


def test_outline_routes_to_authoring_service() -> None:
    hermes = _service()
    outline = "x" * 80

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(outline))

    asyncio.run(_run())
    cast(AsyncMock, hermes._authoring.start_outline).assert_awaited()


def test_collaborator_handles_post_pm_before_authoring() -> None:
    hermes = _service()
    hermes._collaborator.handle_lead_message = AsyncMock(return_value=True)

    async def _run() -> None:
        await hermes.on_room_message(_OPS, _message(f"post-pm {_INIT}"))

    asyncio.run(_run())
    cast(AsyncMock, hermes._collaborator.handle_lead_message).assert_awaited()
    cast(AsyncMock, hermes._authoring.start_outline).assert_not_awaited()


def test_hermes_post_pm_brief_path() -> None:
    assert hermes_post_pm_brief_path(_INIT) == (f"prd/reports/{_INIT}-hermes-post-pm-brief.md")


def test_post_pm_brief_from_hermes_parses_delta_card() -> None:
    body = """# Hermes post-PM brief — INIT-REALWORLD-001

recommend: confirm

## bluf
Proceed — Criticals cleared; deferred identity fields do not undercut stranger-on-home.

## changed
- Promoted PRD metadata now reads as the live SSOT
- Empty-home vs outage wording tightened for readers

## deferred
- Exact identity import fields — attribution may stay thin until named

## still_risky
- none

## example
A stranger reopens home after publish and reads matching title, body, and author name.

## options
- confirm — proceed to impact-map when ready
- revise — hold and edit the PRD
"""
    judgment = post_pm_brief_from_hermes(body)
    assert judgment is not None
    assert judgment.recommend == "confirm"
    assert "Proceed" in judgment.bluf or "proceed" in judgment.bluf.lower()
    assert judgment.recommend_why == judgment.bluf
    assert any("SSOT" in b for b in judgment.changed)
    assert judgment.still_risky == ("none",)


def test_post_pm_brief_from_hermes_rejects_malformed() -> None:
    assert post_pm_brief_from_hermes("") is None
    assert post_pm_brief_from_hermes("# no recommend line\n## bluf\nx\n") is None
    # Promote-shaped locking card is rejected (delta sections required).
    legacy = """recommend: confirm
## bluf
Confirm the job.
## locking
- Restate PRD
## not_locking
- none
## revise_if
- none
## example
Someone publishes.
"""
    assert post_pm_brief_from_hermes(legacy) is None
