"""Gate 2 Spec attest — labels move + APPROVE before merge (delivery parity with PRD)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.programmes.dev import forge_ops
from src.models.hermes.execution_models import ForgeActionResult
from src.models.orchestrator_models import AppRole


def _app(app_id: int = 1) -> AppRole:
    return AppRole(
        app_id=app_id,
        installation_id=10,
        pem="/tmp/x.pem",
        repos=["realworld-api"],
    )


def test_dev_acl_allows_gate2_attest() -> None:
    assert forge_allowed("adh.dev", "approve_attestation")
    assert forge_allowed("adh.dev", "ready_for_review")
    assert forge_allowed("adh.dev", "apply_labels")


@pytest.mark.asyncio
async def test_land_spec_pr_projects_spec_lgtm(monkeypatch: pytest.MonkeyPatch) -> None:
    forge = MagicMock()
    forge.land_pull_request = AsyncMock(
        return_value=ForgeActionResult(
            action="land_pull_request",
            repo="realworld-api",
            pr_number=3,
            url="sha",
        )
    )
    writer = _app(1)
    reviewer = _app(2)
    workspace = MagicMock()
    workspace.app_role = MagicMock(return_value=reviewer)
    monkeypatch.setattr(forge_ops, "app_for_repo", lambda _w, _r: writer)

    await forge_ops.land_spec_pr(
        forge=forge,
        workspace=workspace,
        repo="realworld-api",
        pr_number=3,
        initiative="INIT-REALWORLD-002",
    )
    kwargs = forge.land_pull_request.await_args.kwargs
    assert kwargs["gate_label_add"] == ["spec-lgtm"]
    assert "spec-pending" in kwargs["gate_label_remove"]
    assert kwargs["pre_approve_app"] is reviewer


@pytest.mark.asyncio
async def test_attest_spec_pr_ready_then_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    forge = MagicMock()
    forge.ready_for_review = AsyncMock(
        return_value=ForgeActionResult(
            action="ready_for_review", repo="realworld-api", pr_number=3, url="u"
        )
    )
    forge.approve_attestation = AsyncMock(
        return_value=ForgeActionResult(
            action="approve_attestation", repo="realworld-api", pr_number=3, url="rev"
        )
    )
    writer = _app(1)
    reviewer = _app(2)
    workspace = MagicMock()
    workspace.app_role = MagicMock(return_value=reviewer)
    monkeypatch.setattr(forge_ops, "app_for_repo", lambda _w, _r: writer)

    result = await forge_ops.attest_spec_pr(
        forge=forge,
        workspace=workspace,
        repo="realworld-api",
        pr_number=3,
        initiative="INIT-REALWORLD-002",
    )
    assert result.url == "rev"
    forge.ready_for_review.assert_awaited_once()
    kwargs = forge.approve_attestation.await_args.kwargs
    assert kwargs["label_add"] == ["spec-lgtm"]
    assert "spec-pending" in kwargs["label_remove"]
    assert kwargs["gate_labels"] is True
    assert kwargs["app"] is reviewer


@pytest.mark.asyncio
async def test_land_pull_request_applies_gate_labels_with_approve() -> None:
    from src.infra_services.forge_action_service import ForgeActionService

    github = MagicMock()
    github.installation_token = AsyncMock(return_value=("tok", {}))
    github.mark_ready_for_review = AsyncMock()
    github.merge_pull_request = AsyncMock(return_value="merge-sha")
    github.pull_head_sha = AsyncMock(return_value="abc")
    github.create_pull_review = AsyncMock(return_value="https://review")
    github.replace_issue_labels = AsyncMock()

    svc = ForgeActionService(github=github)
    svc._initialized = True
    writer = _app(1)
    reviewer = _app(2)

    await svc.land_pull_request(
        app=writer,
        repo="realworld-api",
        pr_number=3,
        commit_title="docs: merge",
        pre_approve_app=reviewer,
        pre_approve_body="Gate 2",
        gate_label_add=["spec-lgtm"],
        gate_label_remove=["spec-pending"],
    )
    github.replace_issue_labels.assert_awaited()
    call = github.replace_issue_labels.await_args
    assert call.kwargs["add"] == ["spec-lgtm"]
    assert call.kwargs["remove"] == ["spec-pending"]
    github.merge_pull_request.assert_awaited_once()
