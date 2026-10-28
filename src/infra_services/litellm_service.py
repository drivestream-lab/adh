"""OpenAI-compatible client for LiteLLM (glm / qwen / kimi-k3)."""

import json
from typing import Any, Optional

import httpx
from injector import inject

from src.configs.hermes_settings import HermesSettings
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger

logger = get_logger()


class LiteLLMService(BaseInfraService):
    """Calls LiteLLM chat completions. Cursor CLI does not use this path."""

    @inject
    def __init__(self) -> None:
        self._settings = HermesSettings.get_instance()
        self._client: Optional[httpx.AsyncClient] = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        logger.info(
            "Initializing LiteLLM service",
            base_url=self._settings.litellm_base_url,
            model=self._settings.model,
        )
        self._client = httpx.AsyncClient(timeout=self._settings.timeout_seconds)
        self._initialized = True

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._initialized = False

    async def health_check(self) -> bool:
        if not self._initialized or self._client is None:
            return False
        try:
            root = self._settings.litellm_base_url.rstrip("/").removesuffix("/v1")
            response = await self._client.get(f"{root}/health/liveliness")
            return response.status_code < 500
        except Exception:
            logger.exception("LiteLLM health check failed")
            return False

    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
    ) -> tuple[dict[str, Any], str]:
        """Return (parsed_object, raw_text). Raises on transport failure."""
        if self._client is None:
            raise RuntimeError("LiteLLM service has not been initialized")
        payload = {
            "model": self._settings.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        url = f"{self._settings.litellm_base_url.rstrip('/')}/chat/completions"
        response = await self._client.post(
            url,
            headers={
                "Authorization": f"Bearer {self._settings.litellm_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        raw = _message_text(body)
        try:
            return _parse_json_object(raw), raw
        except ValueError:
            logger.warning("LiteLLM JSON parse failed", preview=raw[:400])
            raise


def _message_text(body: dict[str, Any]) -> str:
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return json.dumps(body)
    for key in ("content", "reasoning_content"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return json.dumps(body)


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = [line for line in lines if not line.startswith("```")]
        text = "\n".join(inner).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
    raise ValueError("LiteLLM did not return a JSON object")
