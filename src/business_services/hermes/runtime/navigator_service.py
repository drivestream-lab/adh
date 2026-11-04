"""Navigate the pinned workflow by outcomes. Human checkpoints are never auto-passed."""

from __future__ import annotations

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.hermes.catalogue.resolve import resolve_next
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.workflow_catalogue_service import WorkflowCatalogueService
from src.models.hermes.catalogue_models import WorkflowNodeDocument
from src.models.hermes.session_models import (
    AWAITING_AUTHORIZATION,
    AWAITING_JUDGMENT,
    AWAITING_NONE,
    HermesSession,
)


class HermesNavigatorService(BaseBusinessService):
    """Thin wrapper over catalogue ``resolve_next`` that keeps session.stage in sync."""

    @inject
    def __init__(self, catalogue: WorkflowCatalogueService) -> None:
        super().__init__()
        self._catalogue = catalogue

    def current(self, session: HermesSession) -> WorkflowNodeDocument:
        if not session.stage:
            raise ValidationError("session has no workflow stage")
        try:
            return self._catalogue.snapshot().node(session.stage)
        except KeyError as exc:
            raise ValidationError(f"unknown workflow stage: {session.stage}") from exc

    def resolve(self, stage: str, outcome: str) -> WorkflowNodeDocument:
        return resolve_next(self._catalogue.snapshot(), stage, outcome)

    def entrypoint_for(self, node_id: str) -> str | None:
        """Entrypoint name whose start node is ``node_id`` (None when not an entrypoint)."""
        for name, start in self._catalogue.snapshot().workflow.entrypoints.items():
            if start == node_id:
                return name
        return None

    def advance(self, session: HermesSession, outcome: str) -> WorkflowNodeDocument:
        """Move ``session.stage`` to the next node and set ``awaiting`` for gated nodes.

        Does not walk past a human checkpoint or an explicit-authorization action:
        the next node is returned and the session is told what it is waiting for.
        """
        nxt = self.resolve(session.stage, outcome)
        session.stage = nxt.node_id
        session.handoff_outcome = outcome
        session.open_brief = None
        if nxt.is_human_checkpoint():
            session.awaiting = AWAITING_JUDGMENT
        elif nxt.is_external_action() and nxt.requires_explicit_authorization():
            session.awaiting = AWAITING_AUTHORIZATION
        else:
            session.awaiting = AWAITING_NONE
        session.touch()
        self.logger.info(
            "Advanced Hermes session",
            slug=session.tenant_slug,
            stage=session.stage,
            outcome=outcome,
            awaiting=session.awaiting,
        )
        return nxt
