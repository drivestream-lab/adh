# ADR 0005 — Hire `adh.coder` (wave / WorkManifest execution)

- **Status:** Proposed → Accepted when C.1–C.19 locked in the sole [implementation plan](../plans/adh-agents-implementation-plan.md)
- **Date:** 2026-11-14
- **Context:** Dev (`adh.dev`) walks `workflow.yaml` **development** through **board-tickets-action** and stops (`board-seeded`). YAML continues with `wave-in-progress-action` → `pre-implement` → `loop-spec` → `wave-pr-action` → acceptance / signoff. That post-board chain is **Coder** territory — execute WorkManifest TASK* into code + draft wave PRs. Identities `adh.coder.*` already exist in Buzz seed; there is no worker/programme yet. E1 explicitly deferred Coder. **Locks + tracker:** only [adh-agents-implementation-plan.md](../plans/adh-agents-implementation-plan.md) (no sibling plan files).

## Decision

1. **Hire `adh.coder`** as a first-class Team OS role (`CoderAgent` + `make adh-coder`), same spine as Dev/PE (BaseHermesAgent + Orchestrator + programme).
2. **Catalogue SSOT** — Coder walks only the YAML nodes after board seed (`wave-in-progress-action` … `wave-complete` / closeout). No invented hops; no dual spine with Dev.
3. **Handoff** — Dev emits **Coder baton(s)** when board seed proofs pass (replace “Coder hire is later” coach) — typically **one baton per Affected repo**. Coders claim on `#engg-<id>` (same engg floor; board Issues are tickets, not a second chat SSOT).
4. **Swarm** — Parallelism = dynamic ready-set ∩ configurable **`max_parallel_coders`** (no hardcoded repo counts). Repo-scoped workers/leases; within a wave, TASK\* serial on one head. No tenant/repo/branch literals.
5. **Behaviour** — Hermes packs `hermes.coder.*` mimic a **human developer review**: MDC/rules by severity (fix P0/P1; defer P2 with why); CAP/J vs PRD+spec with **human titles** (not bare `CAP-01`); fixture packs named `cap-{nn}-<slug>` / `j-{nn}-<slug>`; coverage packet must be legible for a later **QA/verifier** hire; same packs for **human** and **god** GateOpener. Skills stay prayog (`pre-implement`, `loop-spec`, …).
6. **Forge** — `commit_workspace`, `open_draft_pr` (wave), `update_board_status` per YAML; GateOpener only on human-checkpoint nodes (`wave-acceptance`, `wave-signoff`, …).
7. **Verify** — RealWorld guinea pig on a **board-seeded** INIT (prefer INIT-004 human + one god replay). Stratum dry-run fixtures stay pack/parse only until onboard.

## Consequences

- Dev fence remains board-seed; Coder owns coding waves.
- WorkManifest §9 becomes the execution contract Coder must fail-closed on.
- Per-repo coder handles (`adh.coder.realworld-api`, …) map to Impact-Map Affected repos and are the swarm unit.

## Non-goals (this hire)

- Verify / QA / IaC / SRE / Obs agents
- codegraph MCP productization
- Collapsing engg into task room
- Auto-merge of wave PRs (human `wave-signoff`)
