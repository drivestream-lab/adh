"""OpenAI-compatible client for LiteLLM (glm / qwen / kimi-k3 / sonnet)."""

import ast
import json
import re
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
        self._client = httpx.AsyncClient(timeout=self._settings.wait_budget_seconds())
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
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> tuple[dict[str, Any], str]:
        """Return (parsed_object, raw_text). Raises on transport failure."""
        raw = await self.complete(
            system,
            user,
            max_tokens=max_tokens,
            model=model,
            temperature=temperature,
            json_object=True,
        )
        try:
            return _parse_json_object(raw), raw
        except ValueError:
            logger.warning(f"LiteLLM JSON parse failed: {raw[:400]!r}")
            raise

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
        model: Optional[str] = None,
        temperature: float = 0.2,
        json_object: bool = False,
    ) -> str:
        """Return assistant text. json_object is opt-in — think hops write markdown."""
        if self._client is None:
            raise RuntimeError("LiteLLM service has not been initialized")
        alias = (model or self._settings.model).strip()
        payload: dict[str, Any] = {
            "model": alias,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_object:
            payload["response_format"] = {"type": "json_object"}
        url = f"{self._settings.litellm_base_url.rstrip('/')}/chat/completions"
        try:
            response = await self._client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._settings.litellm_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError(
                f"{type(exc).__name__} after {self._settings.wait_budget_seconds():.0f}s "
                f"calling {alias}"
            ) from exc
        response.raise_for_status()
        return _message_text(response.json())


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


_UNQUOTED_KEY = re.compile(r"([\{\[,]\s*)([A-Za-z_][\w]*)\s*:")
_UNQUOTED_VALUE = re.compile(r":\s*([A-Za-z_][\w.-]*)\s*([,}\]])")
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_JSON_LITERALS = {"true", "false", "null"}


def _quote_unquoted_value(match: re.Match[str]) -> str:
    ident = match.group(1)
    if ident in _JSON_LITERALS:
        return match.group(0)
    return f': "{ident}"{match.group(2)}'


def _repair_json_text(text: str) -> str:
    """Quote bare keys/idents and drop trailing commas. Used only after json.loads fails."""
    repaired = _TRAILING_COMMA.sub(r"\1", text)
    repaired = _UNQUOTED_KEY.sub(r'\1"\2":', repaired)
    return _UNQUOTED_VALUE.sub(_quote_unquoted_value, repaired)


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = [line for line in lines if not line.startswith("```")]
        text = "\n".join(inner).strip()
    blobs = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        blobs.append(text[start : end + 1])
    last_err: Optional[Exception] = None
    seen: set[str] = set()
    for blob in blobs:
        for candidate in (blob, _repair_json_text(blob)):
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError as exc:
                last_err = exc
                continue
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                return {"candidates": parsed}
        try:
            parsed = ast.literal_eval(blob)
        except (ValueError, SyntaxError) as exc:
            last_err = last_err or exc
            continue
        if isinstance(parsed, dict):
            return parsed
    preview = (raw or "")[:240]
    raise ValueError(f"LiteLLM did not return a JSON object: {preview!r}") from last_err
