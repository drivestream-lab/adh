"""Prompt templates and structured LLM responses. Prompts live in YAML, not callers."""

from typing import Any, Optional

from pydantic import Field, field_validator

from src.models.base_models import BaseCreateModel


def _text_from_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("decision", "text", "body", "summary", "item", "value"):
            raw = value.get(key)
            if raw:
                ident = str(value.get("id") or "").strip()
                text = str(raw).strip()
                return f"{ident}: {text}" if ident else text
        return ""
    return str(value).strip()


def coerce_string_list(value: Any) -> list[str]:
    """Accept list[str] or list[{id, decision/text}] from the model. Never stall the hop."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [item for item in (_text_from_value(entry) for entry in value) if item]
    text = _text_from_value(value)
    return [text] if text else []


class HermesFinding(BaseCreateModel):
    lane: str = ""
    text: str = ""


class HermesPmBriefResponse(BaseCreateModel):
    summary: str = ""
    journeys: list[str] = Field(default_factory=list)
    reqs_covered: list[str] = Field(default_factory=list)
    findings: list[HermesFinding] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)


class HermesPmOutlineResponse(HermesPmBriefResponse):
    proposed_init: str = ""
    branch_policy: str = ""


class HermesThinkCap(BaseCreateModel):
    id: str = ""
    capability: str = ""
    journeys: list[str] = Field(default_factory=list)
    notes: str = ""


class HermesThinkReq(BaseCreateModel):
    id: str = ""
    cap: str = ""
    requirement: str = ""
    condition: str = ""
    observable: str = ""
    evidence: str = ""


class HermesThinkJourney(BaseCreateModel):
    id: str = ""
    actor: str = ""
    trigger: str = ""
    main_flow: str = ""
    edge: str = ""
    abandon: str = ""
    caps: list[str] = Field(default_factory=list)


class HermesThinkOq(BaseCreateModel):
    id: str = ""
    question: str = ""
    owner: str = "PM"
    blocking: str = "yes"
    required_by: str = "spec-draft"
    default_if_deferred: str = ""


class HermesPmThinkResponse(BaseCreateModel):
    proposed_init: str = ""
    candidate_label: str = "C1"
    job: str = ""
    why_now: str = ""
    if_we_do_nothing: str = ""
    kill_assumption: str = ""
    locked_decisions: list[str] = Field(default_factory=list)
    in_scope: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    capabilities: list[HermesThinkCap] = Field(default_factory=list)
    requirements: list[HermesThinkReq] = Field(default_factory=list)
    journeys: list[HermesThinkJourney] = Field(default_factory=list)
    open_questions: list[HermesThinkOq] = Field(default_factory=list)
    whole_product_delta: str = ""
    equivalent_product_notes: str = ""
    summary: str = ""
    file_body: str = ""

    @field_validator("locked_decisions", "in_scope", "non_goals", mode="before")
    @classmethod
    def _coerce_string_lists(cls, value: Any) -> list[str]:
        return coerce_string_list(value)


class HermesPmBarScore(BaseCreateModel):
    bar: str = ""
    result: str = ""
    material: bool = True
    evidence: str = ""


class HermesPmCandidateScore(BaseCreateModel):
    label: str = ""
    path: str = ""
    handover: str = "no"
    material_fails: list[str] = Field(default_factory=list)
    bars: list[HermesPmBarScore] = Field(default_factory=list)
    spec_lane_guesses: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)


class HermesPmQualityResponse(BaseCreateModel):
    candidates: list[HermesPmCandidateScore] = Field(default_factory=list)
    rank: str = "tie"
    recommend_promote: str = ""
    notes: str = ""
    harness_proposal: str = ""


class HermesEngGradeResponse(BaseCreateModel):
    scores: dict[str, float] = Field(default_factory=dict)
    notes: str = ""
    rca: Optional[str] = None
    harness_proposal: Optional[str] = None


RESPONSE_MODELS: dict[str, type[BaseCreateModel]] = {
    "HermesPmBriefResponse": HermesPmBriefResponse,
    "HermesPmOutlineResponse": HermesPmOutlineResponse,
    "HermesPmThinkResponse": HermesPmThinkResponse,
    "HermesPmQualityResponse": HermesPmQualityResponse,
    "HermesEngGradeResponse": HermesEngGradeResponse,
}


class PromptResponseSpec(BaseCreateModel):
    model: str = Field(..., min_length=1)


class PromptTemplateDocument(BaseCreateModel):
    id: str = Field(..., min_length=3, max_length=128)
    version: str = Field(default="1")
    lane: str = ""
    temperature: float = Field(default=0.2)
    max_tokens: int = Field(default=20000, ge=64, le=32768)
    output: str = Field(default="json", max_length=16)
    system: str = Field(..., min_length=1)
    user: str = Field(..., min_length=1)
    response: PromptResponseSpec
    defaults: dict[str, Any] = Field(default_factory=dict)
    stub: dict[str, Any] = Field(default_factory=dict)


class CopyTemplateDocument(BaseCreateModel):
    """Buzz copy and artifact shells. Same YAML root as LLM prompts, no model call."""

    id: str = Field(..., min_length=3, max_length=128)
    kind: str = "copy"
    version: str = "1"
    body: str = Field(..., min_length=1)


class RenderedPrompt(BaseCreateModel):
    template_id: str
    version: str
    system: str
    user: str
    max_tokens: int = 20000
    response_model: str


class PromptRunResult(BaseCreateModel):
    template_id: str
    version: str
    parsed: dict[str, Any]
    raw: str
    model: str
    stub: bool = False
