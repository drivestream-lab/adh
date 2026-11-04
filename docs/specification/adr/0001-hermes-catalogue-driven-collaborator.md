# ADR 0001 — Hermes catalogue-driven delivery collaborator

- **Status:** Accepted
- **Date:** 2026-11-04
- **Context:** Hermes Lead UX was a dual-track (Buzz prompts + prayog skills) with hardcoded phrase allowlists, hop name tables, and Redis pending sprawl. That debt blocked recommend→judge→execute collaboration and drifted from `sdd-delivery/v2`.

## Decision

1. **SSOT for delivery navigation** is the pinned `prayog-skills/workflow.yaml` (via `.harness-pin.yaml` + local `prayog-skills/` checkout). ADH loads a typed catalogue; it does not maintain skill-id or checkpoint allowlists.
2. **Collaboration loop:** evaluate artefact → recommend with human-level options/examples → Lead judges → Hermes executes (skill hop or forge/GitHub) only after explicit authorization when the node requires it.
3. **No hardcoded delivery vocabulary** in Python as product SSOT (no frozen intent enums, post-pm phrase frozensets, or hop name sets). Structural YAML field names may be typed; node ids, purposes, forge actions, and reply tokens come from the catalogue or the open brief.
4. **Greenfield cutover:** when the orchestrator owns a lane, delete the old walk / pending / allowlist paths in the same PR. No parallel forever.
5. **Forge:** Hermes may open forge/GitHub when Lead authorizes (`authorization: explicit`) or when the pin marks `authorization: automated` — inverting the dual-track “Hermes never opens Forge” note.

## Consequences

- New packages under `src/business_services/hermes/{catalogue,understanding,collaboration,runtime,execution,surface}/` and `WorkflowCatalogueService`.
- Delete on flip (done): `post_promote_walk.py`, post-pm pending keys, `lead_tokens` phrase SSOT, `docs/hermes-pm-dual-track.md`.
- Authoring slice (done): LiteLLM think/quality/ask/recommend prompts deleted; mixin replaced by `AuthoringProgrammeService` using `/prd-think` + `/prd-quality`; ask/recommend pending deleted.
- Prayog remains the workflow owner; ADH is a catalogue consumer (see `docs/specification/references/hermes-catalogue-projection.md`).

## Non-goals

- Hermes is not a coding agent (no “edit feature X” intents).
- ADH does not fork a second workflow graph.
