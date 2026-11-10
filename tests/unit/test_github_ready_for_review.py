"""mark_ready_for_review uses GraphQL — REST …/ready_for_review does not exist."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.infra_services.github_app_service import GitHubAppService


def _response(status: int, payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("GET", "https://api.github.com/test"),
    )


@pytest.mark.asyncio
async def test_mark_ready_noop_when_not_draft() -> None:
    svc = GitHubAppService()
    svc._initialized = True
    svc._client = MagicMock()
    svc._settings = MagicMock()
    svc._settings.github_org = "drivestream-lab"
    svc._settings.github_api = "https://api.github.com"
    svc._request = AsyncMock(return_value=_response(200, {"draft": False, "node_id": "PR_1"}))

    await svc.mark_ready_for_review("tok", "realworld-meta", pr_number=5)

    assert svc._request.await_count == 1
    method, url = svc._request.await_args_list[0].args[:2]
    assert method == "GET"
    assert url.endswith("/repos/drivestream-lab/realworld-meta/pulls/5")


@pytest.mark.asyncio
async def test_mark_ready_uses_graphql_mutation() -> None:
    svc = GitHubAppService()
    svc._initialized = True
    svc._client = MagicMock()
    svc._settings = MagicMock()
    svc._settings.github_org = "drivestream-lab"
    svc._settings.github_api = "https://api.github.com"

    async def _fake(method: str, url: str, **kwargs: Any) -> httpx.Response:
        if method == "GET":
            return _response(200, {"draft": True, "node_id": "PR_kwDOVac9Rs5abc"})
        assert method == "POST"
        assert url.endswith("/graphql")
        body = kwargs.get("json") or {}
        assert "markPullRequestReadyForReview" in body["query"]
        assert body["variables"]["id"] == "PR_kwDOVac9Rs5abc"
        # Must not hit the bogus REST ready_for_review path.
        assert "ready_for_review" not in url
        return _response(
            200,
            {
                "data": {
                    "markPullRequestReadyForReview": {
                        "pullRequest": {"number": 5, "isDraft": False}
                    }
                }
            },
        )

    svc._request = AsyncMock(side_effect=_fake)
    await svc.mark_ready_for_review("tok", "realworld-meta", pr_number=5)
    assert svc._request.await_count == 2


@pytest.mark.asyncio
async def test_mark_ready_surfaces_graphql_errors() -> None:
    svc = GitHubAppService()
    svc._initialized = True
    svc._client = MagicMock()
    svc._settings = MagicMock()
    svc._settings.github_org = "drivestream-lab"
    svc._settings.github_api = "https://api.github.com"

    async def _fake(method: str, url: str, **kwargs: Any) -> httpx.Response:
        if method == "GET":
            return _response(200, {"draft": True, "node_id": "PR_x"})
        return _response(200, {"errors": [{"message": "Resource not accessible by integration"}]})

    svc._request = AsyncMock(side_effect=_fake)
    with pytest.raises(Exception, match="Resource not accessible|markPullRequestReadyForReview"):
        await svc.mark_ready_for_review("tok", "realworld-meta", pr_number=5)
