"""HTTP client to the Buzz conversation plane (host orchestrator → Docker API)."""

from typing import Any, Optional
from uuid import UUID

import httpx

from src.configs.orchestrator_settings import OrchestratorSettings
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger
from src.models.buzz_models import EventType, MessageKind

logger = get_logger()


class BuzzHttpService(BaseInfraService):
    """Posts orchestrator and coder events to Buzz over HTTP."""

    def __init__(self) -> None:
        self._settings = OrchestratorSettings.get_instance()
        self._client: Optional[httpx.AsyncClient] = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._client = httpx.AsyncClient(timeout=15.0)
        self._initialized = True
        logger.info("Initializing Buzz HTTP client", base_url=self._settings.buzz_base_url)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._initialized = False

    async def health_check(self) -> bool:
        return self._initialized and self._client is not None

    async def post_event(
        self,
        handle: str,
        body: str,
        event_type: EventType,
        payload: Optional[dict[str, Any]] = None,
    ) -> Optional[UUID]:
        if self._client is None:
            raise RuntimeError("Buzz HTTP client has not been initialized")
        url = (
            f"{self._settings.buzz_base_url.rstrip('/')}"
            f"/api/v1/buzz/rooms/{self._settings.ops_room}/messages"
        )
        response = await self._client.post(
            url,
            json={
                "identity_handle": handle,
                "body": body,
                "kind": MessageKind.EVENT.value,
                "event_type": event_type.value,
                "payload": payload or {},
            },
        )
        response.raise_for_status()
        raw_id = response.json().get("id")
        return UUID(str(raw_id)) if raw_id else None

    async def ensure_identity(self, handle: str, display_name: str, role: str) -> None:
        if self._client is None:
            raise RuntimeError("Buzz HTTP client has not been initialized")
        url = f"{self._settings.buzz_base_url.rstrip('/')}/api/v1/buzz/identities"
        response = await self._client.post(
            url,
            json={
                "handle": handle,
                "display_name": display_name,
                "kind": "agent",
                "role": role,
            },
        )
        if response.status_code in {200, 201}:
            logger.info("Ensured Buzz identity", handle=handle)
            return
        if response.status_code in {400, 409, 422}:
            logger.info("Buzz identity already present", handle=handle, status=response.status_code)
            return
        response.raise_for_status()

    async def post_hermes_grade(self, *, pr_ref: str, verify_exit: int) -> None:
        if self._client is None:
            raise RuntimeError("Buzz HTTP client has not been initialized")
        url = f"{self._settings.buzz_base_url.rstrip('/')}/api/v1/hermes/eng/grade"
        try:
            response = await self._client.post(
                url,
                json={
                    "pr_ref": pr_ref,
                    "verify_exit": verify_exit,
                    "notes": "Phase H G0 kill — grade after black-box verify.",
                },
                timeout=90.0,
            )
            if response.status_code >= 400:
                logger.info(
                    "Hermes grade returned error",
                    status=response.status_code,
                    body=response.text[:300],
                )
                return
            logger.info("Posted Hermes eng grade", pr_ref=pr_ref, status=response.status_code)
        except Exception:
            logger.exception("Hermes grade failed", pr_ref=pr_ref)

    async def heartbeat(self, handle: str, body: str) -> None:
        if self._client is None:
            raise RuntimeError("Buzz HTTP client has not been initialized")
        url = f"{self._settings.buzz_base_url.rstrip('/')}/api/v1/buzz/heartbeats"
        response = await self._client.post(
            url,
            json={
                "identity_handle": handle,
                "room_slug": self._settings.ops_room,
                "body": body,
                "event_type": EventType.PROGRESS.value,
                "payload": {"service": "orchestrator"},
            },
        )
        response.raise_for_status()
