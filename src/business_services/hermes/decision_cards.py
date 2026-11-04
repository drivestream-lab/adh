"""Merge LLM decision briefs onto frozen validation findings."""

from __future__ import annotations

from typing import Any


_ALLOWED = {"fix", "accept", "reject", "defer"}


def apply_validate_briefs(
    frozen: list[dict[str, Any]],
    card: dict[str, Any],
) -> list[dict[str, Any]]:
    """Freeze id/severity/finding; attach example/options/recommend from card."""
    by_id = {
        str(item.get("id") or ""): item
        for item in card.get("briefs") or []
        if isinstance(item, dict)
    }
    out: list[dict[str, Any]] = []
    for row in frozen:
        item = dict(row)
        fid = str(item.get("id") or "")
        extra = by_id.get(fid) or {}
        item["question"] = str(extra.get("question") or item.get("finding") or fid).strip()
        item["example"] = str(extra.get("example") or "").strip()
        raw_options = extra.get("options")
        options: list[Any] = raw_options if isinstance(raw_options, list) else []
        cleaned_opts: list[dict[str, str]] = []
        for opt in options:
            if not isinstance(opt, dict):
                continue
            choice = str(opt.get("choice") or "").strip().lower()
            if choice not in _ALLOWED:
                continue
            cleaned_opts.append({"choice": choice, "means": str(opt.get("means") or "").strip()})
        if not cleaned_opts:
            cleaned_opts = [
                {"choice": "fix", "means": "Change the PRD to clear this finding."},
                {"choice": "reject", "means": "Leave the PRD as written; accept the risk."},
                {"choice": "defer", "means": "Park it; do not block this promote cycle."},
            ]
        item["options"] = cleaned_opts
        recommend = str(extra.get("recommend") or "fix").strip().lower()
        if recommend not in _ALLOWED:
            recommend = "fix"
        item["recommend"] = recommend
        item["recommend_why"] = str(extra.get("recommend_why") or "").strip()
        if not item["example"]:
            item["example"] = (
                "A visitor or author hits this tomorrow. Decide whether the PRD "
                "must change before engineering drafts."
            )
        if not item["recommend_why"]:
            finding_text = str(item.get("finding") or fid).strip()
            item["recommend_why"] = (
                f"Clear this before update: {finding_text[:160]}"
                if finding_text
                else "Clear the finding so update-documents does not guess."
            )
        out.append(item)
    return out


def format_validate_brief_block(briefs: list[dict[str, Any]]) -> str:
    if not briefs:
        return "(none)"
    chunks: list[str] = []
    for item in briefs:
        fid = str(item.get("id") or "?")
        chunks.append(f"### {fid} ({item.get('severity') or '?'})")
        chunks.append("")
        chunks.append(str(item.get("question") or item.get("finding") or ""))
        chunks.append("")
        chunks.append(f"**In real life.** {item.get('example') or ''}")
        chunks.append("")
        rec = str(item.get("recommend") or "")
        why = str(item.get("recommend_why") or "")
        chunks.append(f"**We recommend.** `{rec}` — {why}")
        chunks.append("")
        chunks.append("| If you choose | What happens |")
        chunks.append("|---------------|--------------|")
        for opt in item.get("options") or []:
            if not isinstance(opt, dict):
                continue
            mark = " ←" if opt.get("choice") == rec else ""
            chunks.append(f"| `{opt.get('choice')}`{mark} | {opt.get('means') or ''} |")
        chunks.append("")
        chunks.append(f"Reply `{fid}: fix` / `reject` / `defer`, or `{fid}: explain`.")
        chunks.append("")
    chunks.append("Or `accept-recs` for this wave only.")
    return "\n".join(chunks)
