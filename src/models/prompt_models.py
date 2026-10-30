"""Prompt templates and structured LLM responses. Prompts live in YAML, not callers."""

import re
from typing import Any, Optional

from pydantic import Field, field_validator, model_validator

from src.models.base_models import BaseCreateModel

_THINK_FILE = re.compile(r"-prd-think(?:-(\d+))?\.md$", re.I)
_C_HEAD = re.compile(r"^##\s+(C\d+)\s*[:\-]?\s*(.*)$", re.I | re.M)
_B_LINE = re.compile(r"\*\*B(\d+)\s*(?:\([^)]*\))?:\*\*\s*(PASS|FAIL|N/?A)", re.I)
_SCORE_LINE = re.compile(
    r"(citation|journeys|req_coverage|findings_quality)\s*[:=]\s*([0-3](?:\.\d+)?)",
    re.I,
)


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


def label_from_think_path(path: str) -> str:
    match = _THINK_FILE.search((path or "").replace("\\", "/"))
    if not match:
        return ""
    run = match.group(1)
    return f"C{run}" if run else "C1"


def quality_has_signal(payload: dict[str, Any]) -> bool:
    for item in payload.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        if item.get("bars") or item.get("scores"):
            return True
    return False


def coerce_quality_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Accept Sonnet's files/rubric_pm_scores/criterion shape as HermesPmQualityResponse."""
    rows = value.get("candidates")
    if not isinstance(rows, list) or not rows:
        for key in ("files", "file_scores", "candidates_by_file"):
            alt = value.get(key)
            if isinstance(alt, list) and alt:
                rows = alt
                break
        else:
            rows = []
    candidates = [_coerce_quality_candidate(item) for item in rows if isinstance(item, dict)]
    return {
        "candidates": candidates,
        "rank": str(value.get("rank") or "tie"),
        "recommend_promote": str(value.get("recommend_promote") or ""),
        "recommendation_why": str(value.get("recommendation_why") or ""),
        "lead_questions": cap_lead_questions(value.get("lead_questions")),
        "notes": str(value.get("notes") or ""),
        "harness_proposal": str(value.get("harness_proposal") or ""),
    }


def quality_from_markdown(raw: str) -> dict[str, Any]:
    """Turn a markdown B-bar writeup into the quality JSON the loop expects."""
    text = (raw or "").strip()
    if not text:
        return {"candidates": []}
    heads = list(_C_HEAD.finditer(text))
    candidates: list[dict[str, Any]] = []
    if not heads:
        bars = _bars_from_markdown(text)
        scores = _scores_from_markdown(text)
        if bars or scores:
            candidates.append(
                {
                    "label": "C1",
                    "path": "",
                    "handover": "no",
                    "bars": bars,
                    "scores": scores,
                    "material_fails": [
                        f"{row['bar']} {row['evidence']}".strip()
                        for row in bars
                        if str(row.get("result") or "").upper() == "FAIL"
                    ],
                }
            )
        return {"candidates": candidates, "rank": "tie", "recommend_promote": ""}
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(text)
        section = text[head.start() : end]
        label = head.group(1).upper()
        rest = (head.group(2) or "").strip()
        path = rest.strip("`").strip()
        bars = _bars_from_markdown(section)
        scores = _scores_from_markdown(section)
        candidates.append(
            {
                "label": label,
                "path": path,
                "handover": "no",
                "bars": bars,
                "scores": scores,
                "material_fails": [
                    f"{row['bar']} {row['evidence']}".strip()
                    for row in bars
                    if str(row.get("result") or "").upper() == "FAIL"
                ],
            }
        )
    return {"candidates": candidates, "rank": "tie", "recommend_promote": ""}


def _coerce_quality_candidate(item: dict[str, Any]) -> dict[str, Any]:
    path = str(item.get("path") or "")
    label = str(item.get("label") or item.get("candidate_label") or "").strip()
    if not label:
        label = label_from_think_path(path)
    scores = item.get("scores") if isinstance(item.get("scores"), dict) else {}
    if not scores and isinstance(item.get("rubric_pm_scores"), dict):
        scores = item["rubric_pm_scores"]
    bars = _bars_from_value(item.get("bars"))
    fails: list[str] = []
    raw_fails = item.get("material_fails")
    if isinstance(raw_fails, list):
        for entry in raw_fails:
            if isinstance(entry, str) and entry.strip():
                fails.append(entry.strip())
                continue
            if not isinstance(entry, dict):
                continue
            bar = str(entry.get("bar") or entry.get("criterion") or "").strip()
            result = str(entry.get("result") or entry.get("finding") or "FAIL").strip().upper()
            evidence = str(entry.get("evidence") or entry.get("finding") or "").strip()
            if bar:
                token = bar.split()[0].upper()
                bars.append(
                    {
                        "bar": token,
                        "result": result if result in {"PASS", "FAIL", "N/A", "NA"} else "FAIL",
                        "material": True,
                        "evidence": evidence,
                    }
                )
                fails.append(f"{bar} {evidence}".strip())
    return {
        "label": label or "C1",
        "path": path,
        "handover": _handover_text(item.get("handover", item.get("handover_ready"))),
        "why": str(item.get("why") or "").strip(),
        "why_not": str(item.get("why_not") or "").strip(),
        "bars": bars,
        "scores": scores,
        "material_fails": fails,
        "spec_lane_guesses": [str(row) for row in (item.get("spec_lane_guesses") or []) if row],
    }


def _handover_text(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False or value is None or value == "":
        return "no"
    text = str(value).strip().lower()
    return "yes" if text in {"yes", "true", "ready", "promote"} else "no"


def _bars_from_value(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        bar = str(entry.get("bar") or entry.get("criterion") or "").strip()
        if not bar:
            continue
        result = str(entry.get("result") or entry.get("finding") or "").strip().upper()
        if result == "NA":
            result = "N/A"
        rows.append(
            {
                "bar": bar.split()[0].upper(),
                "result": result,
                "material": bool(entry.get("material", True)),
                "evidence": str(entry.get("evidence") or "").strip(),
                "pointer": str(entry.get("pointer") or "").strip(),
            }
        )
    return rows


def _bars_from_markdown(section: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for match in _B_LINE.finditer(section or ""):
        result = match.group(2).upper().replace("N/A", "N/A")
        if result == "NA":
            result = "N/A"
        after = (section or "")[match.end() : match.end() + 240].strip()
        evidence = after.split("\n")[0].strip().strip("*").strip('"').strip()
        rows.append(
            {
                "bar": f"B{int(match.group(1))}",
                "result": result,
                "material": True,
                "evidence": evidence,
                "pointer": "",
            }
        )
    return rows


def _scores_from_markdown(section: str) -> dict[str, float]:
    scores: dict[str, float] = {}
    for match in _SCORE_LINE.finditer(section or ""):
        scores[match.group(1).lower()] = float(match.group(2))
    return scores


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
    pointer: str = ""


class HermesPmCandidateScore(BaseCreateModel):
    label: str = ""
    path: str = ""
    handover: str = "no"
    why: str = ""
    why_not: str = ""
    material_fails: list[str] = Field(default_factory=list)
    bars: list[HermesPmBarScore] = Field(default_factory=list)
    spec_lane_guesses: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)


class HermesPmLeadQuestion(BaseCreateModel):
    question: str = ""
    why_it_matters: str = ""
    if_unanswered: str = ""


class HermesPmQualityResponse(BaseCreateModel):
    candidates: list[HermesPmCandidateScore] = Field(default_factory=list)
    rank: str = "tie"
    recommend_promote: str = ""
    recommendation_why: str = ""
    lead_questions: list[HermesPmLeadQuestion] = Field(default_factory=list)
    notes: str = ""
    harness_proposal: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_payload(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return coerce_quality_payload(value)
        return value


_PICK_C = re.compile(r"C(\d+)", re.I)
_MD_H2 = re.compile(r"^##\s+(.+?)\s*$", re.M)
_REC_HEAD = re.compile(r"(?im)^##\s*recommend(?:ation)?\s*[:\-]\s*\**\s*(C\d+|none)")
_REC_INLINE = re.compile(r"(?im)\brecommend(?:ed)?(?:\s+pick)?\s*[:\-]\s*\**\s*(C\d+|none)")
_REC_PATH = re.compile(r"(?im)^(?:\*\*)?path(?:\*\*)?\s*[:\-]\s*`?(.+?)`?\s*$")
_REC_READY = re.compile(r"(?im)engineering[- ]ready\s*[:\-]\s*\**\s*(yes|no)")


def cap_lead_questions(rows: Any, max_questions: int = 3) -> list[dict[str, Any]]:
    """Keep at most max_questions team-raised gaps for the human PM."""
    if not isinstance(rows, list):
        return []
    kept: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or item.get("prompt") or "").strip()
        if not question:
            continue
        kept.append(
            {
                "question": question,
                "why_it_matters": str(item.get("why_it_matters") or item.get("why") or "").strip(),
                "if_unanswered": str(
                    item.get("if_unanswered") or item.get("if_you_skip") or ""
                ).strip(),
            }
        )
        if len(kept) >= max_questions:
            break
    return kept


def ask_card_has_signal(payload: dict[str, Any]) -> bool:
    for item in payload.get("forks") or []:
        if not isinstance(item, dict):
            continue
        if item.get("example") or item.get("recommend") or item.get("choice_rows"):
            return True
    return False


def quality_card_has_signal(payload: dict[str, Any]) -> bool:
    if str(payload.get("recommendation_why") or "").strip():
        return True
    for item in payload.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        if item.get("why") or item.get("why_not"):
            return True
        for bar in item.get("bars") or []:
            if isinstance(bar, dict) and str(bar.get("evidence") or "").strip():
                return True
    return bool(payload.get("lead_questions"))


class HermesPmQualityCardBar(BaseCreateModel):
    bar: str = ""
    evidence: str = ""
    pointer: str = ""


class HermesPmQualityCardCandidate(BaseCreateModel):
    label: str = ""
    why: str = ""
    why_not: str = ""
    bars: list[HermesPmQualityCardBar] = Field(default_factory=list)


class HermesPmQualityCardResponse(BaseCreateModel):
    recommendation_why: str = ""
    lead_questions: list[HermesPmLeadQuestion] = Field(default_factory=list)
    candidates: list[HermesPmQualityCardCandidate] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        rows = value.get("candidates")
        if not isinstance(rows, list):
            rows = []
        candidates = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            bars = []
            for bar in item.get("bars") or []:
                if not isinstance(bar, dict):
                    continue
                bid = str(bar.get("bar") or "").split()[0].upper()
                if not bid:
                    continue
                bars.append(
                    {
                        "bar": bid,
                        "evidence": str(bar.get("evidence") or "").strip(),
                        "pointer": str(bar.get("pointer") or "").strip(),
                    }
                )
            candidates.append(
                {
                    "label": str(item.get("label") or "").strip(),
                    "why": str(item.get("why") or "").strip(),
                    "why_not": str(item.get("why_not") or "").strip(),
                    "bars": bars,
                }
            )
        return {
            "recommendation_why": str(value.get("recommendation_why") or "").strip(),
            "lead_questions": cap_lead_questions(value.get("lead_questions")),
            "candidates": candidates,
        }


def _ask_choice_rows(value: Any) -> tuple[list[str], list[dict[str, str]]]:
    labels: list[str] = []
    rows: list[dict[str, str]] = []
    if not isinstance(value, list):
        labels = coerce_string_list(value)
        return labels, []
    for item in value:
        if isinstance(item, str) and item.strip():
            labels.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        choice = str(item.get("choice") or item.get("label") or item.get("text") or "").strip()
        if not choice:
            continue
        labels.append(choice)
        means = str(
            item.get("means") or item.get("what_it_means") or item.get("example") or ""
        ).strip()
        favours = str(item.get("favours") or item.get("favors") or "").strip()
        if means or favours:
            rows.append({"choice": choice, "means": means, "favours": favours})
    return labels, rows


def cap_ask_forks(forks: Any, max_forks: int = 3) -> list[dict[str, Any]]:
    """Keep at most max_forks closed forks that would change the pick."""
    if not isinstance(forks, list):
        return []
    kept: list[dict[str, Any]] = []
    for item in forks:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or item.get("prompt") or "").strip()
        why = str(
            item.get("why_it_changes_the_pick")
            or item.get("why")
            or item.get("changes_the_pick")
            or ""
        ).strip()
        labels, rows = _ask_choice_rows(item.get("choices") or item.get("options"))
        if not rows and isinstance(item.get("choice_rows"), list):
            _, rows = _ask_choice_rows(item.get("choice_rows"))
        if not question or not why or len(labels) < 2:
            continue
        recommend = str(item.get("recommend") or item.get("we_recommend") or "").strip()
        if recommend and recommend not in labels:
            recommend = ""
        kept.append(
            {
                "id": f"F{len(kept) + 1}",
                "question": question,
                "choices": labels,
                "choice_rows": [row for row in rows if row.get("choice") in labels],
                "example": str(item.get("example") or item.get("real_life") or "").strip(),
                "recommend": recommend,
                "recommend_why": str(
                    item.get("recommend_why") or item.get("why_we_recommend") or ""
                ).strip(),
                "why_it_changes_the_pick": why,
                "quote": str(item.get("quote") or item.get("evidence") or "").strip(),
            }
        )
        if len(kept) >= max_forks:
            break
    return kept


def coerce_ask_card_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Enrichment only. Question/choice strings stay with the frozen ask hop."""
    rows = value.get("forks")
    if not isinstance(rows, list):
        rows = []
    forks: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("id") or "").strip()
        if not fid:
            continue
        labels, choice_rows = _ask_choice_rows(item.get("choices") or item.get("choice_rows"))
        forks.append(
            {
                "id": fid,
                "question": str(item.get("question") or "").strip(),
                "choices": labels,
                "choice_rows": choice_rows,
                "example": str(item.get("example") or item.get("real_life") or "").strip(),
                "recommend": str(item.get("recommend") or item.get("we_recommend") or "").strip(),
                "recommend_why": str(
                    item.get("recommend_why") or item.get("why_we_recommend") or ""
                ).strip(),
                "why_it_changes_the_pick": str(item.get("why_it_changes_the_pick") or "").strip(),
                "quote": "",
            }
        )
    return {"forks": forks, "notes": str(value.get("notes") or "")}


def coerce_ask_payload(value: dict[str, Any], max_forks: int = 3) -> dict[str, Any]:
    rows = value.get("forks")
    if not isinstance(rows, list) or not rows:
        for key in ("questions", "decisions", "forks_for_lead"):
            alt = value.get(key)
            if isinstance(alt, list) and alt:
                rows = alt
                break
        else:
            rows = []
    return {
        "forks": cap_ask_forks(rows, max_forks=max_forks),
        "notes": str(value.get("notes") or ""),
    }


def coerce_recommend_payload(value: dict[str, Any]) -> dict[str, Any]:
    rec = str(value.get("recommend") or value.get("pick") or value.get("label") or "none").strip()
    match = _PICK_C.search(rec)
    if rec.lower() in {"none", "iterate", "skip", ""}:
        rec = "none"
    elif match:
        rec = f"C{match.group(1)}"
    else:
        rec = "none"
    why_not_raw = value.get("why_not") or value.get("rejected") or []
    why_not: list[dict[str, str]] = []
    if isinstance(why_not_raw, list):
        for item in why_not_raw:
            if isinstance(item, dict):
                label = str(item.get("label") or "").strip()
                text = str(
                    item.get("why_not") or item.get("reason") or item.get("text") or ""
                ).strip()
                if label or text:
                    why_not.append({"label": label, "why_not": text})
            elif item:
                why_not.append({"label": "", "why_not": str(item)})
    ready = str(value.get("engineering_ready") or "no").strip().lower()
    if ready not in {"yes", "no"}:
        ready = "no"
    return {
        "recommend": rec,
        "path": str(value.get("path") or ""),
        "why": str(value.get("why") or value.get("reason") or ""),
        "why_not": why_not,
        "residual_locks": coerce_string_list(value.get("residual_locks") or value.get("locks")),
        "engineering_ready": ready,
        "file_body": str(value.get("file_body") or ""),
        "notes": str(value.get("notes") or ""),
    }


def recommend_has_signal(payload: dict[str, Any]) -> bool:
    rec = str(payload.get("recommend") or "").strip().lower()
    if rec == "none" or re.fullmatch(r"c\d+", rec):
        return True
    return bool(str(payload.get("why") or "").strip())


def recommend_from_markdown(raw: str) -> dict[str, Any]:
    """Turn a markdown recommend memo into HermesPmRecommendResponse."""
    text = (raw or "").strip()
    if not text:
        return coerce_recommend_payload({})
    match = _REC_HEAD.search(text) or _REC_INLINE.search(text)
    rec = match.group(1) if match else "none"
    path_match = _REC_PATH.search(text)
    path = path_match.group(1).strip() if path_match else ""
    if path.upper() in {"N/A", "NA", "NONE", "(NONE)"}:
        path = ""
    ready_match = _REC_READY.search(text)
    why_not: list[dict[str, str]] = []
    for line in _markdown_section(text, {"why not", "why-not", "rejected"}).splitlines():
        item = line.strip().lstrip("-").strip()
        if not item or item.lower() == "(none)":
            continue
        if ":" in item:
            label, rest = item.split(":", 1)
            why_not.append({"label": label.strip().strip("*"), "why_not": rest.strip()})
        else:
            why_not.append({"label": "", "why_not": item})
    locks = [
        line.strip().lstrip("-").strip()
        for line in _markdown_section(
            text, {"residual locks", "locks", "residual_locks"}
        ).splitlines()
        if line.strip() and line.strip().lower() not in {"- (none)", "(none)"}
    ]
    return coerce_recommend_payload(
        {
            "recommend": rec,
            "path": path,
            "why": _markdown_section(text, {"why"}),
            "why_not": why_not,
            "residual_locks": locks,
            "engineering_ready": ready_match.group(1) if ready_match else "no",
            "file_body": text if text.startswith("#") else "",
            "notes": _markdown_section(text, {"notes"}),
        }
    )


def _markdown_section(text: str, names: set[str]) -> str:
    heads = list(_MD_H2.finditer(text or ""))
    wanted = {item.lower() for item in names}
    for index, head in enumerate(heads):
        title = re.sub(r"[*`]", "", head.group(1)).strip().lower()
        title = title.split(":")[0].strip()
        if title not in wanted:
            continue
        end = heads[index + 1].start() if index + 1 < len(heads) else len(text)
        return text[head.end() : end].strip()
    return ""


class HermesPmAskChoice(BaseCreateModel):
    choice: str = ""
    means: str = ""
    favours: str = ""


class HermesPmAskFork(BaseCreateModel):
    id: str = ""
    question: str = ""
    choices: list[str] = Field(default_factory=list)
    choice_rows: list[HermesPmAskChoice] = Field(default_factory=list)
    example: str = ""
    recommend: str = ""
    recommend_why: str = ""
    why_it_changes_the_pick: str = ""
    quote: str = ""

    @field_validator("choices", mode="before")
    @classmethod
    def _coerce_choices(cls, value: Any) -> list[str]:
        labels, _rows = _ask_choice_rows(value)
        return labels


class HermesPmAskCardResponse(BaseCreateModel):
    forks: list[HermesPmAskFork] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_payload(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return coerce_ask_card_payload(value)
        return value


class HermesPmAskResponse(BaseCreateModel):
    forks: list[HermesPmAskFork] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_payload(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return coerce_ask_payload(value)
        return value


class HermesPmRecommendWhyNot(BaseCreateModel):
    label: str = ""
    why_not: str = ""


class HermesPmRecommendResponse(BaseCreateModel):
    recommend: str = "none"
    path: str = ""
    why: str = ""
    why_not: list[HermesPmRecommendWhyNot] = Field(default_factory=list)
    residual_locks: list[str] = Field(default_factory=list)
    engineering_ready: str = "no"
    file_body: str = ""
    notes: str = ""

    @field_validator("residual_locks", mode="before")
    @classmethod
    def _coerce_locks(cls, value: Any) -> list[str]:
        return coerce_string_list(value)

    @model_validator(mode="before")
    @classmethod
    def _coerce_payload(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return coerce_recommend_payload(value)
        return value


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
    "HermesPmQualityCardResponse": HermesPmQualityCardResponse,
    "HermesPmAskResponse": HermesPmAskResponse,
    "HermesPmAskCardResponse": HermesPmAskCardResponse,
    "HermesPmRecommendResponse": HermesPmRecommendResponse,
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
