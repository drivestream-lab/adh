"""Mint GitHub App installation tokens. Never merges."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import httpx
from jose import jwt

from src.configs.orchestrator_settings import OrchestratorSettings
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger
from src.models.orchestrator_models import AppRole

logger = get_logger()


class GitHubAppService(BaseInfraService):
    """JWT + installation token. Cursor CLI does not use LiteLLM."""

    def __init__(self) -> None:
        self._settings = OrchestratorSettings.get_instance()
        self._client: Optional[httpx.AsyncClient] = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._client = httpx.AsyncClient(timeout=30.0)
        self._initialized = True
        logger.info("Initializing GitHub App service")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._initialized = False

    async def health_check(self) -> bool:
        return self._initialized and self._client is not None

    async def installation_token(self, app: AppRole, *, write: bool) -> tuple[str, dict[str, Any]]:
        """Return (token, permissions). Read-only dummy tokens cannot merge."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        pem = Path(app.pem).expanduser()
        if not pem.is_file():
            raise ValidationError(f"GitHub App PEM not found: {pem}")
        now = datetime.now(UTC)
        encoded = jwt.encode(
            {
                "iat": int(now.timestamp()) - 10,
                "exp": int((now + timedelta(minutes=8)).timestamp()),
                "iss": str(app.app_id),
            },
            pem.read_text(),
            algorithm="RS256",
        )
        installation_id = app.installation_id
        if installation_id is None:
            installation_id = await self._installation_id(encoded, app.app_id)
        permissions: dict[str, str]
        if write:
            permissions = {
                "contents": "write",
                "pull_requests": "write",
                "checks": "write",
                "metadata": "read",
            }
        else:
            permissions = {"contents": "read", "metadata": "read"}
        url = (
            f"{self._settings.github_api.rstrip('/')}"
            f"/app/installations/{installation_id}/access_tokens"
        )
        response = await self._client.post(
            url,
            headers={
                "Authorization": f"Bearer {encoded}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"permissions": permissions},
        )
        response.raise_for_status()
        body = response.json()
        token = str(body["token"])
        granted = body.get("permissions") or permissions
        logger.info(
            "Minted GitHub App installation token",
            app_id=app.app_id,
            installation_id=installation_id,
            write=write,
            permissions=granted,
        )
        return token, granted

    def merge_forbidden(self, pin_allow_merge: bool, granted: dict[str, Any]) -> bool:
        contents = str(granted.get("contents") or "none")
        return (not pin_allow_merge) or contents != "write"

    async def _installation_id(self, app_jwt: str, app_id: int) -> int:
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        response = await self._client.get(
            f"{self._settings.github_api.rstrip('/')}/app/installations",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        for row in response.json():
            if int(row.get("app_id") or 0) == app_id:
                return int(row["id"])
        raise ValidationError(f"no installation for GitHub App {app_id}")
