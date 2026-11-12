"""Forge create_board_tickets — App tokens only (no gh / user PAT)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.exceptions.app_exceptions import ValidationError
from src.infra_services.forge_action_service import ForgeActionService
from src.models.orchestrator_models import AppRole


def _app() -> AppRole:
    return AppRole(
        app_id=1,
        installation_id=2,
        pem="/tmp/x.pem",
        repos=["realworld-api"],
    )


def _mint_side_effect(*_a: Any, permissions: dict[str, str] | None = None, **_k: Any):
    perms = dict(permissions or {})
    if "organization_projects" in perms:
        return ("proj-tok", {"organization_projects": "write", "metadata": "read"})
    return ("issue-tok", {"issues": "write", "metadata": "read"})


@pytest.mark.asyncio
async def test_create_board_tickets_creates_epic_and_waves(monkeypatch: pytest.MonkeyPatch) -> None:
    github = MagicMock()
    github.installation_token = AsyncMock(side_effect=_mint_side_effect)
    github.repo_has_issues = AsyncMock(return_value=True)
    github.ensure_label = AsyncMock()
    github.resolve_org_project = AsyncMock(
        return_value=("PROJ", 5, "https://github.com/orgs/o/projects/5")
    )
    github.list_issues_by_label = AsyncMock(return_value=[])
    created: list[str] = []

    async def _create(
        token: str, repo: str, *, title: str, body: str, labels: list[str]
    ) -> tuple[int, str, str, int]:
        n = len(created) + 10
        created.append(title)
        return (
            n,
            f"https://github.com/drivestream-lab/{repo}/issues/{n}",
            f"NODE{n}",
            1000 + n,
        )

    github.create_issue = AsyncMock(side_effect=_create)
    github.add_sub_issue = AsyncMock()
    github.add_issue_to_project = AsyncMock()

    svc = ForgeActionService(github)  # type: ignore[arg-type]
    await svc.initialize()

    monkeypatch.setattr(
        "src.configs.orchestrator_settings.OrchestratorSettings.get_instance",
        lambda: MagicMock(github_org="drivestream-lab"),
    )

    result = await svc.create_board_tickets(
        apps=[_app()],
        initiative="INIT-X",
        board_name="RealWorld",
        org="drivestream-lab",
        epic_repo="realworld-api",
        epic_title="EPIC title",
        epic_body="epic",
        labels=["INIT-X"],
        waves=[
            {"id": "W0", "repo": "realworld-api", "title": "W0 title", "body": "w0"},
            {"id": "W1", "repo": "realworld-api", "title": "W1 title", "body": "w1"},
        ],
    )
    assert result.action == "create_board_tickets"
    assert len(result.issue_urls) == 3
    assert all("issues/" in u for u in result.issue_urls)
    assert "EPIC title" in created[0]
    assert github.add_sub_issue.await_count == 2
    assert github.add_issue_to_project.await_count == 3
    # Project GraphQL must use App org-projects token, never a user/gh token.
    for call in github.add_issue_to_project.await_args_list:
        assert call.args[0] == "proj-tok"
    assert "signals.seeded: true" in result.detail


@pytest.mark.asyncio
async def test_create_board_tickets_fails_when_issues_disabled() -> None:
    github = MagicMock()
    github.installation_token = AsyncMock(side_effect=_mint_side_effect)
    github.repo_has_issues = AsyncMock(return_value=False)
    svc = ForgeActionService(github)  # type: ignore[arg-type]
    await svc.initialize()
    with pytest.raises(Exception, match="has_issues=false"):
        await svc.create_board_tickets(
            apps=[_app()],
            initiative="INIT-X",
            board_name="RealWorld",
            org="drivestream-lab",
            epic_repo="realworld-api",
            epic_title="EPIC",
            epic_body="b",
            labels=["INIT-X"],
            waves=[{"id": "W0", "repo": "realworld-api", "title": "W0", "body": "b"}],
        )


@pytest.mark.asyncio
async def test_create_board_tickets_fails_without_org_projects() -> None:
    github = MagicMock()

    async def _issues_only(*_a: Any, permissions: dict[str, str] | None = None, **_k: Any):
        perms = dict(permissions or {})
        if "organization_projects" in perms:
            raise ValidationError("not granted")
        return ("issue-tok", {"issues": "write", "metadata": "read"})

    github.installation_token = AsyncMock(side_effect=_issues_only)
    github.repo_has_issues = AsyncMock(return_value=True)
    github.ensure_label = AsyncMock()
    svc = ForgeActionService(github)  # type: ignore[arg-type]
    await svc.initialize()
    with pytest.raises(ValidationError, match="organization_projects:write"):
        await svc.create_board_tickets(
            apps=[_app()],
            initiative="INIT-X",
            board_name="RealWorld",
            org="drivestream-lab",
            epic_repo="realworld-api",
            epic_title="EPIC",
            epic_body="b",
            labels=["INIT-X"],
            waves=[{"id": "W0", "repo": "realworld-api", "title": "W0", "body": "b"}],
        )


@pytest.mark.asyncio
async def test_ensure_reuses_open_issue_by_title(monkeypatch: pytest.MonkeyPatch) -> None:
    github = MagicMock()
    github.installation_token = AsyncMock(side_effect=_mint_side_effect)
    github.repo_has_issues = AsyncMock(return_value=True)
    github.ensure_label = AsyncMock()
    github.resolve_org_project = AsyncMock(
        return_value=("PROJ", 5, "https://github.com/orgs/o/projects/5")
    )
    github.add_sub_issue = AsyncMock()
    github.add_issue_to_project = AsyncMock()

    async def _list(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        if github.list_issues_by_label.await_count <= 1:
            return [
                {
                    "number": 42,
                    "title": "EPIC title",
                    "html_url": "https://github.com/drivestream-lab/realworld-api/issues/42",
                    "node_id": "NODE42",
                    "id": 4242,
                }
            ]
        return []

    github.list_issues_by_label = AsyncMock(side_effect=_list)
    github.create_issue = AsyncMock(
        return_value=(
            50,
            "https://github.com/drivestream-lab/realworld-api/issues/50",
            "NODE50",
            5050,
        )
    )

    svc = ForgeActionService(github)  # type: ignore[arg-type]
    await svc.initialize()
    monkeypatch.setattr(
        "src.configs.orchestrator_settings.OrchestratorSettings.get_instance",
        lambda: MagicMock(github_org="drivestream-lab"),
    )
    result = await svc.create_board_tickets(
        apps=[_app()],
        initiative="INIT-X",
        board_name="RealWorld",
        org="drivestream-lab",
        epic_repo="realworld-api",
        epic_title="EPIC title",
        epic_body="epic",
        labels=["INIT-X"],
        waves=[{"id": "W0", "repo": "realworld-api", "title": "W0 title", "body": "w0"}],
    )
    assert result.issue_urls[0].endswith("/issues/42")
    assert result.issue_urls[1].endswith("/issues/50")
