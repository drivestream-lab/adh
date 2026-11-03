"""Dumb PM markdown tables and fork/quality render helpers."""

from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

import json
from typing import Any

from src.business_services.hermes.cards import (
    _scorecard_for_card,
    apply_ask_card,
    apply_quality_card,
)
from src.configs.rubrics import RUBRIC_PM
from src.infra_services.pm_workspace_service import quality_path
from src.models.hermes_models import HermesArtifactRead, HermesGradeRequest
from src.models.prompt_models import ask_card_has_signal, quality_card_has_signal


def _format_answers(answers: dict[str, str]) -> str:
    if not answers:
        return "(none — Lead skipped / timed out)"
    skip = answers.get("_skip")
    if skip:
        return f"(skip: {skip})"
    return "\n".join(f"{key}: {value}" for key, value in sorted(answers.items()))


def _format_fork_block(forks: list[Any]) -> str:
    rows = [fork for fork in forks if isinstance(fork, dict)]
    if not rows:
        return "(none)"
    chunks: list[str] = [
        "| Fork | Decision | We recommend |",
        "|------|----------|--------------|",
    ]
    for fork in rows:
        fid = str(fork.get("id") or "?")
        chunks.append(
            "| "
            + " | ".join(
                [
                    fid,
                    _md_cell(fork.get("question") or ""),
                    _md_cell(fork.get("recommend") or "(you choose)"),
                ]
            )
            + " |"
        )
    for fork in rows:
        fid = str(fork.get("id") or "?")
        parts = [f"### {fid}", "", _md_cell(fork.get("question") or "")]
        example = str(fork.get("example") or "").strip()
        if example:
            parts.extend(["", f"**In real life.** {example}"])
        recommend = str(fork.get("recommend") or "").strip()
        recommend_why = str(fork.get("recommend_why") or "").strip()
        if recommend:
            why = f" — {recommend_why}" if recommend_why else ""
            parts.extend(["", f"**We recommend.** {recommend}{why}"])
        choice_rows = [
            item
            for item in (fork.get("choice_rows") or [])
            if isinstance(item, dict) and item.get("choice")
        ]
        labels = [str(item) for item in fork.get("choices") or []]
        parts.extend(["", "| If you choose | What happens |", "|---------------|--------------|"])
        if choice_rows:
            for item in choice_rows:
                mark = " ←" if item.get("choice") == recommend else ""
                parts.append(
                    f"| {_md_cell(item.get('choice'))}{mark} | {_md_cell(item.get('means') or '')} |"
                )
        else:
            for choice in labels:
                mark = " ←" if choice == recommend else ""
                parts.append(f"| {_md_cell(choice)}{mark} |  |")
        parts.extend(["", f"Reply `{fid}: <choice>` using the exact text in the table."])
        chunks.extend(["", *parts])
    return "\n".join(chunks)


def _format_why_not(rows: list[Any]) -> str:
    if not rows:
        return "- (none)"
    lines: list[str] = []
    for item in rows:
        if isinstance(item, dict):
            label = item.get("label") or "?"
            lines.append(f"- {label}: {item.get('why_not') or ''}")
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _format_ready_files(files: list[dict[str, str]]) -> str:
    chunks: list[str] = []
    for item in files:
        label = item.get("label") or "?"
        path = item.get("path") or ""
        body = item.get("file_body") or "(empty file)"
        chunks.append(f"### {label} `{path}`\n{body}")
    return "\n\n".join(chunks) if chunks else "(none)"


def _prior_candidate_text(artifact: HermesArtifactRead) -> str:
    body = str(artifact.payload.get("file_body") or "").strip()
    if body:
        return body
    parsed = artifact.payload.get("artifact") or {}
    if isinstance(parsed, dict):
        return json.dumps(parsed)
    return str(parsed or "")


def _think_file_ref(artifact: HermesArtifactRead) -> dict[str, str]:
    parsed = dict(artifact.payload.get("artifact") or {})
    return {
        "label": str(parsed.get("candidate_label") or "C1"),
        "path": str(artifact.payload.get("path") or ""),
        "file_body": str(artifact.payload.get("file_body") or ""),
    }


def _fail_list_from_quality(artifact: HermesArtifactRead) -> str:
    parsed = artifact.payload.get("artifact") or {}
    fails: list[str] = []
    for cand in parsed.get("candidates") or []:
        label = cand.get("label") or "?"
        for item in cand.get("material_fails") or []:
            fails.append(f"{label}: {item}")
    return "; ".join(fails) if fails else "(none)"


_BAR_ORDER = [f"B{index}" for index in range(1, 16)]


def _quality_copy_vars(
    initiative: str,
    parsed: dict[str, Any],
    path: str,
    model: str,
    pass_number: int,
    max_passes: int,
) -> dict[str, Any]:
    candidates = [row for row in (parsed.get("candidates") or []) if isinstance(row, dict)]
    promote = _quality_promote_label(parsed)
    return {
        "initiative": initiative,
        "model": model,
        "threshold_x": RUBRIC_PM["threshold_x"],
        "rank": parsed.get("rank") or "tie",
        "pass_number": pass_number,
        "max_passes": max_passes,
        "path": path,
        "recommend_promote": parsed.get("recommend_promote") or "none",
        "headline": _format_quality_headline(parsed, promote, pass_number, max_passes),
        "recommendation_why": parsed.get("recommendation_why") or "(none)",
        "questions_table": _format_lead_questions(parsed.get("lead_questions") or []),
        "recommend_table": _format_quality_recommend_table(candidates, promote),
        "evidence_heading": promote,
        "evidence_block": _format_quality_evidence(candidates, promote),
        "scorecard": _format_quality_scorecard(candidates),
        "notes": parsed.get("notes") or "(none)",
        "harness_proposal": parsed.get("harness_proposal") or "(none)",
    }


def _quality_promote_label(parsed: dict[str, Any]) -> str:
    rec = str(parsed.get("recommend_promote") or "").strip()
    if rec and rec.lower() not in {"none", "tie", ""}:
        return rec
    for cand in parsed.get("candidates") or []:
        if isinstance(cand, dict) and str(cand.get("handover") or "").lower() == "yes":
            return str(cand.get("label") or "none")
    return "none"


def _md_cell(text: Any) -> str:
    raw = " ".join(str(text or "").split()).replace("|", "/")
    return raw or "(none)"


def _format_quality_headline(
    parsed: dict[str, Any], promote: str, pass_number: int, max_passes: int
) -> str:
    yes = [
        str(cand.get("label"))
        for cand in parsed.get("candidates") or []
        if isinstance(cand, dict) and str(cand.get("handover") or "").lower() == "yes"
    ]
    yes_txt = ", ".join(yes) if yes else "none"
    rank = parsed.get("rank") or "tie"
    return (
        "Hermes evaluator — so you can judge the candidates fairly. "
        "Rank is not permission to promote.\n\n"
        "| Field | Value |\n"
        "|-------|-------|\n"
        f"| Rank | {rank} — **not** the validate signal |\n"
        f"| Handover-yes | {yes_txt} |\n"
        f"| Recommend (label only) | **{promote}** |\n"
        f"| Ready pass | {pass_number}/{max_passes} |\n"
        "| Your job | Name the file, or none, or iterate. I will not merge. |"
    )


def _why_row(cand: dict[str, Any]) -> str:
    return str(cand.get("why") or "").strip() or (
        "Engineering-ready."
        if str(cand.get("handover") or "").lower() == "yes"
        else "Not engineering-ready."
    )


def _why_not_row(cand: dict[str, Any]) -> str:
    return str(cand.get("why_not") or "").strip() or "(none)"


def _format_lead_questions(rows: list[Any]) -> str:
    questions = [item for item in rows if isinstance(item, dict) and item.get("question")]
    if not questions:
        return "(none)"
    lines = [
        "| # | Question | Why it matters | If you skip |",
        "|---|----------|----------------|-------------|",
    ]
    for index, item in enumerate(questions, start=1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _md_cell(item.get("question")),
                    _md_cell(item.get("why_it_matters") or "(none)"),
                    _md_cell(item.get("if_unanswered") or "(none)"),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _format_quality_recommend_table(candidates: list[dict[str, Any]], promote: str) -> str:
    if not candidates:
        return "(none)"
    lines = [
        "| Candidate | File | Handover | Overall | Why | Why not |",
        "|-----------|------|----------|---------|-----|---------|",
    ]
    for cand in candidates:
        label = str(cand.get("label") or "?")
        path = str(cand.get("path") or "")
        file_cell = f"`{path}`" if path else "(none)"
        handover = str(cand.get("handover") or "no")
        if handover == "yes":
            handover = "**yes**"
        overall = cand.get("overall")
        overall_txt = f"{overall}/3" if overall is not None and overall != "" else "—"
        pick = label.upper() == promote.upper() and promote.lower() != "none"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"**{label} ←**" if pick else label,
                    file_cell,
                    handover,
                    overall_txt,
                    _md_cell(_why_row(cand)),
                    _md_cell(_why_not_row(cand)),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _bars_by_id(cand: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for bar in cand.get("bars") or []:
        if not isinstance(bar, dict):
            continue
        bid = str(bar.get("bar") or "").split()[0].upper()
        if bid:
            out[bid] = bar
    return out


def _bar_table(cand: dict[str, Any], *, fails_only: bool) -> str:
    mapped = _bars_by_id(cand)
    rows = [
        "| Bar | Result | What this means |",
        "|-----|--------|-----------------|",
    ]
    used = False
    for bid in _BAR_ORDER:
        bar = mapped.get(bid)
        if not bar:
            continue
        result = str(bar.get("result") or "").upper() or "—"
        if fails_only and result != "FAIL":
            continue
        used = True
        rows.append(f"| {bid} | {result} | {_md_cell(bar.get('evidence') or '')} |")
    return "\n".join(rows) if used else "(none)"


def _format_quality_evidence(candidates: list[dict[str, Any]], promote: str) -> str:
    if not candidates:
        return "(none)"
    by_label = {str(cand.get("label") or ""): cand for cand in candidates}
    chunks: list[str] = []
    promote_cand = by_label.get(promote)
    if promote_cand and promote.lower() not in {"", "none"}:
        chunks.append(_bar_table(promote_cand, fails_only=False))
    else:
        chunks.append(
            "No handover-yes candidate. FAIL rows below are why none is engineering-ready."
        )
    others = [
        cand for cand in candidates if str(cand.get("label") or "").upper() != promote.upper()
    ]
    if others:
        chunks.append("### Why not the others")
        for cand in others:
            label = cand.get("label") or "?"
            path = cand.get("path") or ""
            chunks.append(f"**{label}** `{path}`\n\n" + _bar_table(cand, fails_only=True))
    return "\n\n".join(chunks)


def _format_quality_scorecard(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "(none)"
    labels = [str(cand.get("label") or "?") for cand in candidates]
    maps = [_bars_by_id(cand) for cand in candidates]
    header = "| Bar | " + " | ".join(labels) + " |"
    divider = "|-----|" + "|".join(["------" for _ in labels]) + "|"
    lines = [header, divider]
    for bid in _BAR_ORDER:
        cells = []
        for mapped in maps:
            bar = mapped.get(bid)
            cells.append(str(bar.get("result") or "—").upper() if bar else "—")
        if all(cell == "—" for cell in cells):
            continue
        lines.append("| " + bid + " | " + " | ".join(cells) + " |")
    return "\n".join(lines) if len(lines) > 2 else "(none)"


def _numbered(value: Any) -> str:
    if not value:
        return "(none)"
    if not isinstance(value, list):
        return f"1. {value}"
    lines = [f"{index}. {item}" for index, item in enumerate(value, start=1)]
    return "\n".join(lines) if lines else "(none)"


def _format_caps(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "- (none)"
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            lines.append(f"- {item}")
            continue
        journeys = ", ".join(str(j) for j in item.get("journeys") or []) or "none"
        notes = str(item.get("notes") or "").strip()
        extra = f" — {notes}" if notes else ""
        lines.append(
            f"- {item.get('id') or '?'}: {item.get('capability') or ''} " f"(J: {journeys}){extra}"
        )
    return "\n".join(lines)


def _format_reqs(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "- (none)"
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            lines.append(f"- {item}")
            continue
        lines.append(
            f"- {item.get('id') or '?'}/{item.get('cap') or '?'}: "
            f"{item.get('requirement') or ''} | when {item.get('condition') or 'n/a'} "
            f"→ {item.get('observable') or 'n/a'} "
            f"(evidence: {item.get('evidence') or 'n/a'})"
        )
    return "\n".join(lines)


def _format_journeys(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "- (none)"
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            lines.append(f"- {item}")
            continue
        caps = ", ".join(str(c) for c in item.get("caps") or []) or "none"
        lines.append(
            f"- {item.get('id') or '?'}: {item.get('actor') or '?'} / "
            f"{item.get('trigger') or '?'} → {item.get('main_flow') or '?'} "
            f"(edge: {item.get('edge') or 'n/a'}; abandon: {item.get('abandon') or 'n/a'}; "
            f"CAP: {caps})"
        )
    return "\n".join(lines)


def _format_oqs(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "- (none)"
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            lines.append(f"- {item}")
            continue
        lines.append(
            f"- {item.get('id') or '?'}: {item.get('question') or ''} "
            f"(owner={item.get('owner') or 'PM'}; blocking={item.get('blocking') or 'yes'}; "
            f"by {item.get('required_by') or 'spec-draft'})"
        )
    return "\n".join(lines)


def _bullets(value: Any) -> str:
    if not value:
        return "- (none)"
    if not isinstance(value, list):
        return f"- {value}"
    lines: list[str] = []
    for item in value:
        if isinstance(item, dict):
            lane = str(item.get("lane") or "").strip()
            text = str(item.get("text") or "").strip()
            lines.append(f"- {lane}: {text}" if lane else f"- {text}")
        else:
            lines.append(f"- {item}")
    return "\n".join(lines) if lines else "- (none)"


class RenderPmMixin:
    """Instance render/card helpers used by HermesService and the walk mixin."""

    def _raise_if_stub(self, artifact: HermesArtifactRead, hop: str) -> None:
        reason = str(artifact.payload.get("raw") or "").strip() or "no JSON object"
        if artifact.payload.get("stub") or artifact.payload.get("model") == "stub":
            raise TimeoutError(
                self._copy("hermes.pm.error.stub-hop", {"hop": hop, "reason": reason})
            )
        if str(artifact.initiative).endswith("-PENDING") or artifact.initiative == "INIT-PENDING":
            raise TimeoutError(self._copy("hermes.pm.error.pending-init", {"hop": hop}))

    def _think_copy_vars(
        self,
        initiative: str,
        label: str,
        parsed: dict[str, Any],
        path: str,
        *,
        model: str = "",
        numbered_locked: bool = False,
    ) -> dict[str, Any]:
        locked = parsed.get("locked_decisions")
        return {
            "initiative": initiative,
            "label": label,
            "path": path or f"prd/reports/{initiative}-prd-think.md",
            "model": model,
            "short": str(parsed.get("summary") or parsed.get("job") or "prd-think candidate").split(
                "\n"
            )[0],
            "job": parsed.get("job") or "(none)",
            "why_now": parsed.get("why_now") or "(none)",
            "if_we_do_nothing": parsed.get("if_we_do_nothing") or "(none)",
            "kill_assumption": parsed.get("kill_assumption") or "(none)",
            "locked_decisions": (_numbered(locked) if numbered_locked else _bullets(locked)),
            "in_scope": _bullets(parsed.get("in_scope")),
            "non_goals": _bullets(parsed.get("non_goals")),
            "capabilities": _format_caps(parsed.get("capabilities")),
            "requirements": _format_reqs(parsed.get("requirements")),
            "journeys": _format_journeys(parsed.get("journeys")),
            "open_questions": _format_oqs(parsed.get("open_questions")),
            "whole_product_delta": parsed.get("whole_product_delta") or "(none)",
            "equivalent_product_notes": parsed.get("equivalent_product_notes") or "(none)",
            "summary": parsed.get("summary") or "(none)",
        }

    def _render_think_hop_body(
        self,
        initiative: str,
        label: str,
        parsed: dict[str, Any],
        model: str,
        path: str,
    ) -> str:
        return self._copy(
            "hermes.pm.hop.think",
            self._think_copy_vars(initiative, label, parsed, path, model=model),
        )

    def _render_think_hop(self, artifact: HermesArtifactRead) -> str:
        parsed = dict(artifact.payload.get("artifact") or {})
        path = str(artifact.payload.get("path") or "")
        label = str(parsed.get("candidate_label") or "C1")
        model = str(artifact.payload.get("model") or artifact.model or "unresolved")
        file_body = str(artifact.payload.get("file_body") or "").strip()
        if file_body.startswith("#"):
            excerpt = "\n".join(file_body.splitlines()[:28])
            return (
                f"Think {label}  {artifact.initiative}\n"
                f"path: {path}\n"
                f"model={model}  ·  not scored  ·  Hermes will not merge\n\n"
                f"{excerpt}\n…"
            )
        return self._render_think_hop_body(artifact.initiative, label, parsed, model, path)

    def _render_think_file(
        self, initiative: str, label: str, parsed: dict[str, Any], path: str
    ) -> str:
        return self._copy(
            "hermes.pm.file.think",
            self._think_copy_vars(initiative, label, parsed, path, numbered_locked=True),
        )

    async def _apply_quality_card(
        self,
        initiative: str,
        parsed: dict[str, Any],
        files: list[dict[str, str]],
        outline: str,
        model: str,
    ) -> dict[str, Any]:
        """LLM memo for the human PM. Frozen scores. No programme-specific rewrite."""
        card = await self._prompts.complete(
            "hermes.pm.quality.card",
            {
                "initiative": initiative,
                "outline": (outline or "").strip() or "(none)",
                "scorecard": json.dumps(_scorecard_for_card(parsed), ensure_ascii=False),
                "files": _format_ready_files(files),
                "max_questions": 3,
            },
            model=model,
        )
        if not quality_card_has_signal(card.parsed):
            raise TimeoutError(
                self._copy("hermes.pm.error.quality-card", {"initiative": initiative})
            )
        merged = apply_quality_card(parsed, dict(card.parsed))
        self.logger.info(
            "Hermes quality card applied",
            initiative=initiative,
            questions=len(merged.get("lead_questions") or []),
            model=card.model,
        )
        return merged

    async def _apply_ask_card(
        self,
        initiative: str,
        parsed: dict[str, Any],
        files: list[dict[str, str]],
        outline: str,
        model: str,
    ) -> dict[str, Any]:
        """LLM decision aid on frozen forks. Does not change questions or choice strings."""
        try:
            card = await self._prompts.complete(
                "hermes.pm.ask.card",
                {
                    "initiative": initiative,
                    "outline": (outline or "").strip() or "(none)",
                    "forks": json.dumps(
                        [
                            {
                                "id": fork.get("id"),
                                "question": fork.get("question"),
                                "choices": fork.get("choices") or [],
                            }
                            for fork in parsed.get("forks") or []
                            if isinstance(fork, dict)
                        ],
                        ensure_ascii=False,
                    ),
                    "files": _format_ready_files(files),
                },
                model=model,
            )
        except Exception:
            self.logger.exception("Hermes ask card failed", initiative=initiative)
            return parsed
        if not ask_card_has_signal(card.parsed):
            self.logger.warning("Hermes ask card returned no examples", initiative=initiative)
            return parsed
        merged = apply_ask_card(parsed, dict(card.parsed))
        self.logger.info(
            "Hermes ask card applied",
            initiative=initiative,
            forks=len(merged.get("forks") or []),
            model=card.model,
        )
        return merged

    def _render_quality_hop_body(
        self,
        initiative: str,
        parsed: dict[str, Any],
        model: str,
        pass_number: int = 1,
        max_passes: int = 2,
        path: str = "",
    ) -> str:
        return self._copy(
            "hermes.pm.hop.quality",
            _quality_copy_vars(
                initiative, parsed, path or quality_path(initiative), model, pass_number, max_passes
            ),
        )

    def _render_quality_hop(self, artifact: HermesArtifactRead) -> str:
        parsed = dict(artifact.payload.get("artifact") or {})
        model = str(artifact.payload.get("model") or artifact.model or "unresolved")
        return self._render_quality_hop_body(
            artifact.initiative,
            parsed,
            model,
            int(artifact.payload.get("pass_number") or 1),
            int(artifact.payload.get("max_passes") or 2),
            str(artifact.payload.get("path") or quality_path(artifact.initiative)),
        )

    def _render_quality_file(
        self,
        initiative: str,
        parsed: dict[str, Any],
        path: str,
        model: str,
        pass_number: int = 1,
        max_passes: int = 2,
    ) -> str:
        return self._copy(
            "hermes.pm.file.quality",
            _quality_copy_vars(initiative, parsed, path, model, pass_number, max_passes),
        )

    def _render_ask_hop_body(self, initiative: str, parsed: dict[str, Any], model: str) -> str:
        forks = parsed.get("forks") or []
        return self._copy(
            "hermes.pm.hop.ask",
            {
                "initiative": initiative,
                "model": model,
                "fork_count": len(forks),
                "fork_block": _format_fork_block(forks),
                "notes": parsed.get("notes") or "(none)",
            },
        )

    def _render_ask_hop(self, artifact: HermesArtifactRead) -> str:
        parsed = dict(artifact.payload.get("artifact") or {})
        model = str(artifact.payload.get("model") or artifact.model or "unresolved")
        return self._render_ask_hop_body(artifact.initiative, parsed, model)

    def _render_ask_file(self, initiative: str, parsed: dict[str, Any], path: str) -> str:
        forks = parsed.get("forks") or []
        return self._copy(
            "hermes.pm.file.ask",
            {
                "initiative": initiative,
                "path": path,
                "fork_count": len(forks),
                "fork_block": _format_fork_block(forks),
                "notes": parsed.get("notes") or "(none)",
            },
        )

    def _render_recommend_hop_body(
        self, initiative: str, parsed: dict[str, Any], model: str
    ) -> str:
        return self._copy(
            "hermes.pm.hop.recommend",
            {
                "initiative": initiative,
                "model": model,
                "recommend": parsed.get("recommend") or "none",
                "engineering_ready": parsed.get("engineering_ready") or "no",
                "path": parsed.get("path") or "(none)",
                "why": parsed.get("why") or "(none)",
                "why_not": _format_why_not(parsed.get("why_not") or []),
                "residual_locks": _bullets(parsed.get("residual_locks")),
                "notes": parsed.get("notes") or "(none)",
            },
        )

    def _render_recommend_hop(self, artifact: HermesArtifactRead) -> str:
        parsed = dict(artifact.payload.get("artifact") or {})
        model = str(artifact.payload.get("model") or artifact.model or "unresolved")
        return self._render_recommend_hop_body(artifact.initiative, parsed, model)

    def _render_recommend_file(self, initiative: str, parsed: dict[str, Any], path: str) -> str:
        return self._copy(
            "hermes.pm.file.recommend",
            {
                "initiative": initiative,
                "recommend": parsed.get("recommend") or "none",
                "path": parsed.get("path") or "(none)",
                "engineering_ready": parsed.get("engineering_ready") or "no",
                "file_path": path,
                "why": parsed.get("why") or "(none)",
                "why_not": _format_why_not(parsed.get("why_not") or []),
                "residual_locks": _bullets(parsed.get("residual_locks")),
                "notes": parsed.get("notes") or "(none)",
            },
        )

    def _render_brief(
        self, initiative: str, parsed: dict[str, Any], overall: float, model: str
    ) -> str:
        return self._copy(
            "hermes.pm.hop.brief",
            {
                "initiative": initiative,
                "overall": overall,
                "model": model,
                "summary": parsed.get("summary") or "PM brief",
            },
        )

    def _render_grade(
        self,
        request: HermesGradeRequest,
        parsed: dict[str, Any],
        overall: float,
        recommend: bool,
        model: str,
    ) -> str:
        return self._copy(
            "hermes.eng.hop.grade",
            {
                "pr_ref": request.pr_ref,
                "verify_exit": request.verify_exit,
                "overall": overall,
                "threshold_x": self._settings.threshold_x,
                "merge": "recommend merge" if recommend else "do not merge",
                "model": model,
                "notes": parsed.get("notes") or parsed.get("rca") or "grade recorded",
            },
        )
