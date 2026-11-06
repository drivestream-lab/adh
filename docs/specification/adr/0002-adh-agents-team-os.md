# ADR 0002 — ADH Agents Team OS (Buzz multi-agent delivery)

- **Status:** Accepted — Wave 0a live; Wave 0b greenfield control plane (this train)
- **Date:** 2026-11-05 (Wave 0a on develop 2026-11-06; OS extraction 2026-11-06)
- **Context:** PM lane proved delivery on Buzz. Engg/Gate‑1 and later roles need a **scalable multi-agent team OS**, not logic bolted into a Hermes facade. RealWorld is the guinea pig only — **ADH is the product**.

## Decision

1. **ADH is an agent software-engineering team control plane.** Roles (pm, pe, read, kb, later dev/qa/iac/sre/obs) are first-class Buzz identities that collaborate via **batons** / **rollups** and a shared **Orchestrator**, on the pinned `workflow.yaml` graph (ADR 0001).
2. **Greenfield package `src/adh_agents/`** is the only Team OS home: runtime (Orchestrator, work store, stall, catch-up), batons, forge ACL, ports, programmes, role agents. **No legacy shims** — delete `HermesService` router facade, `Orchestrator`, hermes session store, PendingMixin, and unused hermes/pin orchestrator APIs in the same cut.
3. **Control plane vs agent vs programme**
   - **Control plane** (`adh_agents/runtime`): Orchestrator, work sessions, ask-back, resume, stop, catalogue bind, runner registry.
   - **Agent** (process): Buzz identity, listen, baton I/O, forge ACL — **embeds** the control plane.
   - **Programme**: role work registered on the plane (`start` / `after_judgment` / `resume`).
4. **One OS process per role** — `make adh-pm` / `adh-pe` / `adh-read` / `adh-kb` → `adh_*_worker`. Every role worker **embeds** Orchestrator (role-scoped work keys); ops messages are handled only when they match that role’s open work, registered programmes, or inbound batons.
5. **Work sessions in Redis:** `adh:agent:work:{tenant}:{role}:{work_id}` (+ per-role index). TTL covers Lead think-time. Parallel work units + ask-back are OS attributes, not PM-only.
6. **Baton transport:** Buzz = talk/trigger; Redis = claim/idempotency (`adh:baton:{tenant}:{key}`).
7. **Hire order / verify gate:** Prove **PM** on the new OS first (guinea pig), then hand off via `pe.review` to **PE** (fan-out **read**), then PM merge glue, then **kb**.
8. **Code reader is an agent**; codegraph MCP / grep are tools behind ports.
9. **KB writes** via **kb** agent only; OKF heads under tenant meta `knowledge/` — no initiative folders.
10. **Forge ACL per role** — PE attests Gate‑1; PM merges PRD; read/kb cannot Approve/merge.

## Consequences

- Single merge train: move PM programmes under `adh_agents/`, rewrite `PMAgent` onto Orchestrator, delete hermes business runtime / facade / dead APIs.
- PE/read/kb hire onto the same plane — no second router.
- Debt refused: PendingMixin sprawl, dual session stores, soft deprecation re-exports, INIT-hardcoded orchestrator.

## Non-goals

- Replacing MetaGPT/ChatDev-style one-shot app builders.
- Building codegraph indexing inside ADH (MCP/fleet owns graphs).
- Optimizing for a specific RealWorld PR — guinea pig only.
