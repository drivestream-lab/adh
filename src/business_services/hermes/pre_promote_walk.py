"""Pre-promote PM walk helpers.

Authoring loop methods (`_walk_pm_authoring`, `_ask_pass`, `_recommend_pass`,
`_ask_then_recommend`, quality loop) live on `HermesService` and call into
`lead_tokens`, `gates`, `cards`, `render_pm`, and `pending`. This module is the
named home for walk-adjacent pure helpers used by that facade.
"""

from __future__ import annotations

from typing import Optional

from src.business_services.hermes.render_pm import _format_answers, _think_file_ref
from src.models.hermes_models import HermesArtifactRead


def think_paths_from_artifacts(thinks: list[HermesArtifactRead]) -> list[str]:
    return [str(_think_file_ref(item)["path"]) for item in thinks if _think_file_ref(item)["path"]]


def format_lead_answers_for_recommend(answers: Optional[dict[str, str]]) -> str:
    return _format_answers(dict(answers or {}))


def promote_dest(initiative: str) -> str:
    return f"prd/{initiative}.md"
