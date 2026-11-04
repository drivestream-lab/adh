"""Catalogue-backed understanding scaffold (Wave 2).

Binds Lead text to workflow nodes by id/purpose/skill description — no ADH
intent enums. LLM ranking lands in a later slice; this slice exposes catalogue
lookups and slot digs so orchestrator work can start without lead_tokens SSOT.
"""

from __future__ import annotations

import re

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.infra_services.workflow_catalogue_service import WorkflowCatalogueService
from src.models.hermes.catalogue_models import CatalogueSnapshot, WorkflowNodeDocument
from src.models.hermes.intent_models import ClarifyRequest, IntentCandidate

_INIT_TOKEN = re.compile(r"\b(INIT-[A-Z0-9]+-\d+)\b", re.I)


class HermesUnderstandService(BaseBusinessService):
    """Resolve Lead speech against the loaded workflow catalogue."""

    @inject
    def __init__(self, catalogue: WorkflowCatalogueService) -> None:
        super().__init__()
        self._catalogue = catalogue

    def catalogue(self) -> CatalogueSnapshot:
        return self._catalogue.snapshot()

    def candidates_for_node_mention(self, body: str) -> list[IntentCandidate]:
        """Exact / substring match on node_id or purpose — no phrase allowlist.

        Returns ranked candidates when Lead names a catalogue id or purpose
        slug. Missing ``initiative`` is always listed when an INIT token is
        absent so callers can dig.
        """
        text = (body or "").strip()
        if not text:
            return []
        lowered = text.lower()
        snap = self.catalogue()
        found: list[IntentCandidate] = []
        for node in snap.workflow.nodes.values():
            score = _mention_score(lowered, node)
            if score <= 0:
                continue
            slots: dict[str, str] = {}
            missing: list[str] = []
            initiative = _extract_initiative(text)
            if initiative:
                slots["initiative"] = initiative
            else:
                missing.append("initiative")
            found.append(
                IntentCandidate(
                    node_id=node.node_id,
                    confidence=score,
                    rationale=f"matched catalogue node type={node.type}",
                    missing_slots=missing,
                    slots=slots,
                )
            )
        found.sort(key=lambda c: c.confidence, reverse=True)
        return found

    def extract_initiative(self, text: str) -> str | None:
        """INIT-… token from free text (uppercased), or None."""
        return _extract_initiative(text)

    def clarify_for(self, candidates: list[IntentCandidate]) -> ClarifyRequest | None:
        if not candidates:
            return None
        missing = sorted({slot for c in candidates for slot in c.missing_slots})
        if not missing:
            return None
        if "initiative" in missing:
            question = (
                "Which initiative should I use? Reply with an INIT-… id "
                "(example: INIT-REALWORLD-001)."
            )
        else:
            question = f"Need more detail for: {', '.join(missing)}."
        return ClarifyRequest(
            question=question,
            missing_slots=missing,
            candidates=candidates[:5],
        )

    def entrypoint_node(self, entrypoint_name: str) -> WorkflowNodeDocument:
        snap = self.catalogue()
        node_id = snap.entrypoint(entrypoint_name)
        return snap.node(node_id)


def _mention_score(lowered_body: str, node: WorkflowNodeDocument) -> float:
    nid = node.node_id.lower()
    if nid and nid in lowered_body:
        return 0.95
    purpose = (node.purpose or "").lower()
    if purpose and purpose in lowered_body:
        return 0.85
    # Hyphen/space variants of node id
    spaced = nid.replace("-", " ")
    if spaced and spaced in lowered_body:
        return 0.9
    return 0.0


def _extract_initiative(text: str) -> str | None:
    match = _INIT_TOKEN.search(text)
    if match is None:
        return None
    return match.group(1).upper()
