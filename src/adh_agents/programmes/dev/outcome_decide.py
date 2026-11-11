"""After a catalogue skill/action — prompt Hermes to pick a YAML outcome."""

from __future__ import annotations

from typing import Sequence

from src.adh_agents.programmes.dev.labeled_extract import extract_allowed
from src.configs.hermes_settings import HermesSettings
from src.infra_services.litellm_service import LiteLLMService


async def decide_catalogue_outcome(
    litellm: LiteLLMService,
    *,
    node_id: str,
    initiative: str,
    allowed_outcomes: Sequence[str],
    evidence: str,
) -> str:
    """Prompt → extract ``outcome:`` ∈ allowed. Fail closed to ``failed`` if listed else first."""
    allowed = [o.strip() for o in allowed_outcomes if (o or "").strip()]
    if not allowed:
        raise ValueError(f"node {node_id!r} has no outcomes to decide")

    hermes = HermesSettings.get_instance()
    model = (hermes.eng_model or hermes.model or "qwen").strip()
    prompt = "\n".join(
        [
            f"You are adh.dev deciding the workflow.yaml outcome for node `{node_id}`",
            f"on initiative `{initiative}`.",
            "Allowed outcomes (pick exactly one):",
            ", ".join(f"`{o}`" for o in allowed),
            "",
            "Evidence (skill/forge output excerpt):",
            (evidence or "")[:12000] or "(none)",
            "",
            "Emit ONLY labeled lines:",
            "outcome: <exactly one allowed outcome>",
            "why: <one sentence>",
        ]
    )
    text = await litellm.complete(
        "Decide one catalogue outcome. Emit labeled lines only.",
        prompt,
        model=model,
        temperature=0.2,
    )
    picked = extract_allowed(text or "", field="outcome", allowed=allowed)
    if picked:
        return picked
    if "failed" in allowed:
        return "failed"
    if "blocked" in allowed:
        return "blocked"
    return allowed[0]
