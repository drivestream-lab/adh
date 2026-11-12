"""Quality and ask card merges for Hermes PM (no regex)."""

from __future__ import annotations

from typing import Any

from src.models.prompt_models import cap_lead_questions


def _is_c_label(token: str) -> bool:
    t = (token or "").strip().upper().strip("*").strip("`")
    return len(t) >= 2 and t[0] == "C" and t[1:].isdigit()


def _human_pm_text(text: str) -> str:
    """Think-file labels stay off the Lead card. Factory-wide, not programme-specific."""
    raw = (text or "").strip()
    if not raw:
        return ""
    words: list[str] = []
    for part in raw.split():
        core = part.strip(".,;:()[]\"'")
        if _is_c_label(core):
            words.append("this")
        else:
            words.append(part)
    cleaned = " ".join(words)
    lower = cleaned.lower()
    marker = "this proves"
    idx = lower.find(marker)
    if idx >= 0:
        cleaned = cleaned[:idx] + "This proves" + cleaned[idx + len(marker) :]
    while "  " in cleaned:
        cleaned = cleaned.replace("  ", " ")
    return cleaned.strip()


def apply_ask_card(frozen: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """Merge examples onto frozen forks. Never change question or choice strings."""
    merged = dict(frozen)
    by_id = {
        str(item.get("id") or ""): item
        for item in card.get("forks") or []
        if isinstance(item, dict)
    }
    forks: list[dict[str, Any]] = []
    for fork in merged.get("forks") or []:
        if not isinstance(fork, dict):
            continue
        row = dict(fork)
        extra = by_id.get(str(row.get("id") or "")) or {}
        labels = [str(item) for item in row.get("choices") or []]
        if extra.get("example"):
            row["example"] = _human_pm_text(str(extra.get("example") or ""))
        recommend = str(extra.get("recommend") or "").strip()
        if recommend in labels:
            row["recommend"] = recommend
        if extra.get("recommend_why"):
            row["recommend_why"] = _human_pm_text(str(extra.get("recommend_why") or ""))
        choice_rows: list[dict[str, str]] = []
        for item in extra.get("choice_rows") or extra.get("choices") or []:
            if isinstance(item, str):
                continue
            if not isinstance(item, dict):
                continue
            choice = str(item.get("choice") or "").strip()
            if choice not in labels:
                continue
            choice_rows.append(
                {
                    "choice": choice,
                    "means": _human_pm_text(str(item.get("means") or "")),
                    "favours": str(item.get("favours") or "").strip(),
                }
            )
        if choice_rows:
            row["choice_rows"] = choice_rows
        forks.append(row)
    merged["forks"] = forks
    if card.get("notes"):
        merged["notes"] = _human_pm_text(str(card.get("notes") or ""))
    return merged


def apply_quality_card(scored: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """Merge the PM memo onto frozen scores. Never change PASS/FAIL/handover/rank."""
    merged = dict(scored)
    why = str(card.get("recommendation_why") or "").strip()
    if why:
        merged["recommendation_why"] = why
    questions = cap_lead_questions(card.get("lead_questions"))
    if questions:
        merged["lead_questions"] = questions
    by_label = {
        str(item.get("label") or ""): item
        for item in card.get("candidates") or []
        if isinstance(item, dict)
    }
    candidates: list[dict[str, Any]] = []
    for cand in merged.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        row = dict(cand)
        extra = by_label.get(str(row.get("label") or "")) or {}
        if extra.get("why"):
            row["why"] = str(extra.get("why") or "").strip()
        if extra.get("why_not"):
            row["why_not"] = str(extra.get("why_not") or "").strip()
        card_bars = {
            str(bar.get("bar") or "").split()[0].upper(): bar
            for bar in extra.get("bars") or []
            if isinstance(bar, dict)
        }
        bars: list[dict[str, Any]] = []
        for bar in row.get("bars") or []:
            if not isinstance(bar, dict):
                continue
            item = dict(bar)
            rewrite = card_bars.get(str(item.get("bar") or "").split()[0].upper()) or {}
            if rewrite.get("evidence"):
                item["evidence"] = str(rewrite.get("evidence") or "").strip()
            if "pointer" in rewrite:
                item["pointer"] = str(rewrite.get("pointer") or "").strip()
            bars.append(item)
        row["bars"] = bars
        candidates.append(row)
    merged["candidates"] = candidates
    return merged


def _scorecard_for_card(parsed: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    for cand in parsed.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        candidates.append(
            {
                "label": cand.get("label"),
                "path": cand.get("path"),
                "handover": cand.get("handover"),
                "overall": cand.get("overall"),
                "material_fails": cand.get("material_fails") or [],
                "bars": [
                    {
                        "bar": bar.get("bar"),
                        "result": bar.get("result"),
                        "evidence": bar.get("evidence"),
                    }
                    for bar in cand.get("bars") or []
                    if isinstance(bar, dict)
                ],
            }
        )
    return {
        "rank": parsed.get("rank"),
        "recommend_promote": parsed.get("recommend_promote"),
        "candidates": candidates,
    }
