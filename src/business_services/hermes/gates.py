"""Ready and recommend gates for Hermes PM artifacts."""

from __future__ import annotations

from typing import Any

from src.configs.rubrics import RUBRIC_PM, weighted_overall
from src.infra_services.pm_workspace_service import skeleton_material_fails
from src.models.hermes_models import HermesArtifactRead
from src.models.prompt_models import cap_lead_questions


def _any_handover(artifact: HermesArtifactRead) -> bool:
    parsed = artifact.payload.get("artifact") or {}
    return any(
        str(cand.get("handover") or "").lower() == "yes" for cand in parsed.get("candidates") or []
    )


def _as_float_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for key, raw in value.items():
        try:
            out[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


_MATERIAL_BARS = {
    "B1",
    "B2",
    "B3",
    "B4",
    "B5",
    "B6",
    "B8",
    "B9",
    "B10",
    "B11",
    "B12",
    "B14",
    "B15",
}


def apply_ready_gate(parsed: dict[str, Any], files: list[dict[str, str]]) -> dict[str, Any]:
    """Merge LLM B-bar with code skeleton FAILs. Empty B-table cannot be handover yes."""
    by_label = {str(item.get("label") or ""): item for item in files}
    raw = parsed.get("candidates")
    if not isinstance(raw, list):
        raw = []
    candidates: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "")
        source = by_label.get(label) or {}
        path = str(item.get("path") or source.get("path") or "")
        body = str(source.get("file_body") or "")
        skel = skeleton_material_fails(body)
        raw_bars = item.get("bars")
        bars_in: list[Any] = raw_bars if isinstance(raw_bars, list) else []
        bar_rows: list[dict[str, Any]] = []
        fails: list[str] = [str(fail) for fail in (item.get("material_fails") or []) if fail]
        for bar in bars_in:
            if not isinstance(bar, dict):
                continue
            bid = str(bar.get("bar") or "").strip().split()[0].upper()
            result = str(bar.get("result") or "").strip().upper()
            evidence = str(bar.get("evidence") or "")
            material = bool(bar.get("material", bid in _MATERIAL_BARS))
            bar_rows.append(
                {
                    "bar": bid or str(bar.get("bar") or ""),
                    "result": result,
                    "material": material,
                    "evidence": evidence,
                    "pointer": str(bar.get("pointer") or "").strip(),
                }
            )
            if result == "FAIL" and (material or bid in _MATERIAL_BARS):
                fails.append(f"{bid} {evidence}".strip())
        if not bar_rows:
            for fail in skel:
                bid = fail.split()[0]
                bar_rows.append({"bar": bid, "result": "FAIL", "material": True, "evidence": fail})
        fails.extend(skel)
        unique = list(dict.fromkeys(fails))
        scores = _as_float_map(item.get("scores"))
        handover = str(item.get("handover") or "no").strip().lower()
        if unique:
            handover = "no"
        candidates.append(
            {
                "label": label,
                "path": path,
                "handover": "yes" if handover == "yes" else "no",
                "why": str(item.get("why") or "").strip(),
                "why_not": str(item.get("why_not") or "").strip(),
                "material_fails": unique,
                "bars": bar_rows,
                "spec_lane_guesses": [str(row) for row in (item.get("spec_lane_guesses") or [])],
                "scores": scores,
                "overall": weighted_overall(scores, RUBRIC_PM),
            }
        )
    parsed["candidates"] = candidates
    parsed["recommendation_why"] = str(parsed.get("recommendation_why") or "").strip()
    parsed["lead_questions"] = cap_lead_questions(parsed.get("lead_questions"))
    yes_labels = [cand["label"] for cand in candidates if cand["handover"] == "yes"]
    recommend = str(parsed.get("recommend_promote") or "").strip().upper()
    allowed = {label.upper() for label in yes_labels}
    if recommend not in allowed:
        parsed["recommend_promote"] = yes_labels[0] if len(yes_labels) == 1 else ""
    return parsed


def apply_recommend_gate(
    parsed: dict[str, Any],
    files: list[dict[str, str]],
    quality: HermesArtifactRead,
) -> dict[str, Any]:
    """Force none when the label is unknown. Handover-no files cannot be engineering-ready."""
    by_label = {str(item.get("label") or "").upper(): item for item in files}
    rec = str(parsed.get("recommend") or "none").strip().upper()
    if rec in by_label:
        parsed["recommend"] = rec
        parsed["path"] = str(parsed.get("path") or by_label[rec].get("path") or "")
    else:
        parsed["recommend"] = "none"
        parsed["path"] = ""
        parsed["engineering_ready"] = "no"
    if not _any_handover(quality):
        parsed["engineering_ready"] = "no"
    ready = str(parsed.get("engineering_ready") or "no").strip().lower()
    parsed["engineering_ready"] = "yes" if ready == "yes" else "no"
    return parsed
