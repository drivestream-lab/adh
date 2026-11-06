# ADR 0002 — ADH Agents Team OS (Buzz multi-agent delivery)

- **Status:** Accepted for Wave 0a (PM on base); Wave 0b+ still planned
- **Date:** 2026-11-05 (Wave 0a landed on develop 2026-11-06, PRs #6–#12)
- **Context:** PM Hermes lane is live (catalogue collaborator, draft PRD PR). Engg/Gate‑1 and later QA/IaC/SRE need a **scalable multi-agent team**, not more logic bolted into `MetaPmProgrammeService`. Humans and agents collaborate on Buzz; individuals are hired incrementally into the tenant ops channel.

## Decision

1. **ADH is an agent software-engineering team control plane.** Roles (pm, pe, read, kb, later dev/qa/iac/sre/obs) are first-class Buzz identities that collaborate via structured **batons** and **rollups**, on top of the pinned `workflow.yaml` delivery graph (ADR 0001).
2. **Greenfield package `src/adh_agents/`** owns the Team OS: baton store, roster, base worker loop, tool ports, forge ACL. Do **not** invent digesters as private functions inside PE.
3. **One OS process per role** (incremental hire). PM keeps the existing worker; PE/read/kb get dedicated workers.
4. **Baton transport:** Buzz carries talk + trigger + human authorize; **Redis** stores baton state and idempotency (`adh:baton:{tenant}:{key}`).
5. **Code reader is an agent**; codegraph MCP / grep / read are **tools** behind ports (degraded filesystem now; MCP later).
6. **KB writes** go through a **kb agent** (Buzz-triggered), OKF heads only under tenant meta `knowledge/` — no initiative folders.
7. **Leverage, don’t rewrite:** Buzz, catalogue, navigator, forge, Cursor runner, workspace, PM programmes stay. PM only **emits/consumes batons** at handoff seams (e.g. after `open_draft_pr`).
8. **Forge ACL per role** — e.g. only PE attests Gate‑1; only PM merges PRD; read/kb cannot Approve/merge.

## Consequences

- New docs: Team OS implementation plan, KB heads reference, product section for engg swarm.
- New code under `src/adh_agents/` + role workers; extend GitHub App for ready/Approve/labels as needed.
- Debt to avoid carrying into the swarm: `PendingMixin` sprawl, in-process PE digests, INIT-centric KB, second workflow graph in Python.
- Later roles (dev/qa/iac/sre) plug into the same OS; QA docker-verify-on-PR is a planned programme on this spine, not a special cron.

## Non-goals

- Replacing MetaGPT/ChatDev-style one-shot app builders.
- Rewriting the live PM authoring/validate lane as a precondition for PE.
- Building codegraph indexing inside ADH (MCP/fleet owns graphs).
