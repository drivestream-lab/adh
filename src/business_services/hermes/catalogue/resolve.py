"""Workflow navigation — outcomes only, no ADH hop tables."""

from __future__ import annotations

from src.exceptions.app_exceptions import ValidationError
from src.models.hermes.catalogue_models import CatalogueSnapshot, WorkflowNodeDocument


def resolve_next(
    catalogue: CatalogueSnapshot,
    stage: str,
    outcome: str,
) -> WorkflowNodeDocument:
    """Return the next node for ``catalogue.nodes[stage].outcomes[outcome]``.

    Matches delivery-contract consumer algorithm. Does not auto-advance
    human checkpoints — callers must stop when ``next.is_human_checkpoint()``.
    """
    stage_id = (stage or "").strip()
    outcome_key = (outcome or "").strip()
    if not stage_id:
        raise ValidationError("workflow stage is required")
    if not outcome_key:
        raise ValidationError("workflow outcome is required")
    try:
        current = catalogue.node(stage_id)
    except KeyError as exc:
        raise ValidationError(f"unknown workflow stage: {stage_id}") from exc
    next_id = current.outcomes.get(outcome_key)
    if next_id is None or not str(next_id).strip():
        raise ValidationError(
            f"stage {stage_id!r} has no outcome {outcome_key!r}",
        )
    try:
        return catalogue.node(str(next_id).strip())
    except KeyError as exc:
        raise ValidationError(
            f"outcome {outcome_key!r} on {stage_id!r} points to missing node {next_id!r}",
        ) from exc
