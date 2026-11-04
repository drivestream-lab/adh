"""PM / eng Buzz markdown render helpers (authoring hops retired)."""

from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

from typing import Any

from src.models.hermes_models import HermesGradeRequest


class RenderPmMixin:
    """Brief + eng-grade copy rendering used by HermesService."""

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
