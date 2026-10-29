"""Load YAML prompt templates, render variables, validate structured responses."""

import asyncio
import copy
import json
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from injector import inject

from src.configs.hermes_settings import HermesSettings
from src.configs.prompt_settings import PromptSettings
from src.exceptions.app_exceptions import NotFoundError, ValidationError
from src.infra_services.base_infra_service import BaseInfraService
from src.infra_services.litellm_service import LiteLLMService, _parse_json_object
from src.logging import get_logger
from src.models.prompt_models import (
    RESPONSE_MODELS,
    CopyTemplateDocument,
    PromptRunResult,
    PromptTemplateDocument,
    RenderedPrompt,
)

logger = get_logger()

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
_MD_FENCE = re.compile(r"```(?:markdown|md)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


class PromptService(BaseInfraService):
    """Prompt SSOT. Callers pass template id + variables, never inline system text."""

    @inject
    def __init__(self, litellm: LiteLLMService) -> None:
        self._litellm = litellm
        self._settings = PromptSettings.get_instance()
        self._hermes = HermesSettings.get_instance()
        self._templates: dict[str, PromptTemplateDocument] = {}
        self._copy: dict[str, CopyTemplateDocument] = {}
        self._complete_gate = asyncio.Semaphore(max(1, int(self._hermes.litellm_concurrency)))
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        root = self._settings.templates_root()
        self._templates, self._copy = _load_prompt_root(root)
        self._initialized = True
        logger.info(
            "Prompt service loaded templates",
            root=str(root),
            ids=sorted(self._templates),
            copy_ids=sorted(self._copy),
        )

    async def close(self) -> None:
        self._templates = {}
        self._copy = {}
        self._initialized = False

    async def health_check(self) -> bool:
        return self._initialized and bool(self._templates)

    def get(self, template_id: str) -> PromptTemplateDocument:
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise NotFoundError("prompt template", template_id) from exc

    def render_copy(self, template_id: str, variables: Optional[dict[str, Any]] = None) -> str:
        try:
            spec = self._copy[template_id]
        except KeyError as exc:
            raise NotFoundError("copy template", template_id) from exc
        return _render(spec.body, variables or {})

    def render(self, template_id: str, variables: dict[str, Any]) -> RenderedPrompt:
        spec = self.get(template_id)
        merged = {**spec.defaults, **variables}
        return RenderedPrompt(
            template_id=spec.id,
            version=spec.version,
            system=_render(spec.system, merged),
            user=_render(spec.user, merged),
            max_tokens=spec.max_tokens,
            response_model=spec.response.model,
        )

    def parse_response(self, template_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        spec = self.get(template_id)
        model_cls = RESPONSE_MODELS.get(spec.response.model)
        if model_cls is None:
            raise ValidationError(f"unknown prompt response model {spec.response.model}")
        try:
            parsed = model_cls.model_validate(payload)
        except Exception as exc:
            raise ValidationError(
                f"prompt response failed schema {spec.response.model}: {exc}"
            ) from exc
        return parsed.model_dump()

    async def complete(
        self,
        template_id: str,
        variables: dict[str, Any],
        *,
        model: Optional[str] = None,
        json_object: Optional[bool] = None,
    ) -> PromptRunResult:
        """Render and call LiteLLM. Markdown templates are not json_object-gated."""
        spec = self.get(template_id)
        rendered = self.render(template_id, variables)
        alias = (model or self._hermes.model_for_lane(spec.lane or "pm")).strip()
        want_json = (
            spec.output.strip().lower() != "markdown" if json_object is None else json_object
        )
        raw = ""
        try:
            async with self._complete_gate:
                if want_json:
                    parsed, raw = await self._litellm.complete_json(
                        rendered.system,
                        rendered.user,
                        max_tokens=rendered.max_tokens,
                        model=alias,
                        temperature=spec.temperature,
                    )
                    validated = self.parse_response(template_id, parsed)
                else:
                    raw = await self._litellm.complete(
                        rendered.system,
                        rendered.user,
                        max_tokens=rendered.max_tokens,
                        model=alias,
                        temperature=spec.temperature,
                        json_object=False,
                    )
                    validated = _parse_markdown_or_json(self, template_id, raw, variables)
            return PromptRunResult(
                template_id=spec.id,
                version=spec.version,
                parsed=validated,
                raw=raw,
                model=alias,
                stub=False,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Prompt complete fell back to stub",
                template_id=template_id,
                error=str(exc),
                preview=(raw or str(exc))[:400],
            )
            stub = copy.deepcopy(spec.stub)
            findings = stub.get("findings")
            if isinstance(findings, list):
                findings.append({"lane": "eng", "text": _llm_error_text(exc)})
            validated = self.parse_response(template_id, stub)
            return PromptRunResult(
                template_id=spec.id,
                version=spec.version,
                parsed=validated,
                raw=(raw or str(exc))[:8000],
                model="stub",
                stub=True,
            )


def _load_prompt_root(
    root: Path,
) -> tuple[dict[str, PromptTemplateDocument], dict[str, CopyTemplateDocument]]:
    if not root.is_dir():
        raise NotFoundError("prompt root", str(root))
    loaded: dict[str, PromptTemplateDocument] = {}
    copies: dict[str, CopyTemplateDocument] = {}
    for path in sorted(root.glob("*.yaml")):
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        if not isinstance(data, dict):
            raise ValidationError(f"prompt YAML {path.name} is not a mapping")
        kind = str(data.get("kind") or "")
        if kind == "copy-catalog":
            _ingest_copy_catalog(path.name, data, copies)
            continue
        if kind == "copy":
            spec = CopyTemplateDocument.model_validate(data)
            if spec.id in copies:
                raise ValidationError(f"duplicate copy id {spec.id}")
            copies[spec.id] = spec
            continue
        spec = PromptTemplateDocument.model_validate(data)
        if spec.response.model not in RESPONSE_MODELS:
            raise ValidationError(
                f"prompt {spec.id} response.model {spec.response.model} is not registered"
            )
        if spec.id in loaded:
            raise ValidationError(f"duplicate prompt id {spec.id}")
        loaded[spec.id] = spec
    if not loaded:
        raise ValidationError(f"no prompt YAML in {root}")
    return loaded, copies


def _ingest_copy_catalog(
    name: str,
    data: dict[str, Any],
    copies: dict[str, CopyTemplateDocument],
) -> None:
    templates = data.get("templates")
    if not isinstance(templates, dict) or not templates:
        raise ValidationError(f"copy catalog {name} has no templates")
    for template_id, item in templates.items():
        if isinstance(item, str):
            body = item
        elif isinstance(item, dict) and item.get("body"):
            body = item["body"]
        else:
            raise ValidationError(f"copy template {template_id} needs a body")
        key = str(template_id)
        if key in copies:
            raise ValidationError(f"duplicate copy id {key}")
        copies[key] = CopyTemplateDocument(id=key, body=str(body))


def _render(template: str, variables: dict[str, Any]) -> str:
    missing: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            missing.append(key)
            return match.group(0)
        value = variables[key]
        if isinstance(value, (list, dict)):
            return json.dumps(value)
        return str(value)

    rendered = _PLACEHOLDER.sub(_replace, template)
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise ValidationError(f"prompt missing variables: {names}")
    return rendered


def _llm_error_text(exc: Exception) -> str:
    """Never emit a blank 'LLM error:' — httpx timeouts often have empty str()."""
    detail = " ".join(str(exc).split())
    if not detail:
        detail = type(exc).__name__
    return f"{type(exc).__name__}: {detail}"[:400]


def extract_markdown(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    match = _MD_FENCE.search(text)
    if match:
        return match.group(1).strip()
    return text


def _looks_like_json(raw: str) -> bool:
    text = (raw or "").strip()
    if text.startswith("```json"):
        return True
    if text.startswith("{") and text.endswith("}"):
        return True
    return text.startswith("{") and ("proposed_init" in text or "locked_decisions" in text)


def _parse_markdown_or_json(
    service: PromptService,
    template_id: str,
    raw: str,
    variables: dict[str, Any],
) -> dict[str, Any]:
    """Think hops: markdown is the handoff. JSON is accepted and coerced, never required."""
    if _looks_like_json(raw):
        parsed = _parse_json_object(raw)
        return service.parse_response(template_id, parsed)
    body = extract_markdown(raw)
    heading = ""
    for line in body.splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            break
    return {
        "proposed_init": str(variables.get("initiative") or ""),
        "candidate_label": str(variables.get("label") or "C1"),
        "summary": heading,
        "file_body": body,
    }
