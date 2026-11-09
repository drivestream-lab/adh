# Implementation plan — ADH Agents Team OS

**Status:** D1–D2 merged ([PR #17](https://github.com/drivestream-lab/adh/pull/17)); **D3–D5 in flight** on `feature/adh-agents-d3-d4-d5` (agentic locks #18–#19).  
**ADR:** [0002](../adr/0002-adh-agents-team-os.md)  
**Product:** [adh-agents-team-os.md](../product/adh-agents-team-os.md)  
**KB heads:** [adh-kb-heads.md](../references/adh-kb-heads.md)  
**As-built:** [implementation-status.md](../as-built/implementation-status.md)

This is the **work tracker SSOT**. Architecture framing: Team OS control plane + role workers — not a Hermes facade router.  
**Collab UX** from the north-star “Hermes enabler + responsibility agents” plan still binds: recommend + artefact, human conversational gates, **Buzz light** (see below).

---

## Work tracker (follow this)

```text
ADH Agents Team OS

0.  Product / ADR lock                              ✅
0a. PM on BaseHermesAgent + baton emit              ✅  PRs #6–#14
0b. Greenfield control plane + delete legacy        ✅  PR #16 (merge; #15 closed for branch rename)
    - Orchestrator + work store + workers
    - PM programmes on plane
    - pe / read / kb hired (minimal)

── verify gate (block treating PE as “done”) ──
V1. PM live on new OS (RealWorld guinea pig)        ✅  ask-back/resume/gates/authorize → PR #2
V2. PE claims pe.review → read.walk                 ✅  catch-up + live claim → read rollup

── depth (same OS — not new architecture) ──
D1. PE: Q caps (≤10 / ≤4 rounds), Buzz+PR, attest   ✅  PR #17; guinea pig PR #2
D2. PM glue: answer PE + prd_merge authorize        ✅  PR #17; meta PR #2 merged
D3. Read: real repo walks / richer ports            ✅  one-repo repo_ref + structured artefact
D4. KB: actual knowledge/ head patches              ✅  stub+LLM + post-merge emit + enrich PR gate
D5. Harden: dup batons, timeout, wrong authorize    ✅  reclaim + brief tokens + no regex SSOT + SSE-safe

── later hires ──
dev / qa / iac / sre / obs + codegraph MCP          ⬜
```

**Rule:** architecture is closed after 0b. Remaining work deepens programmes on this spine.  
**Product rule:** ADH is the product; RealWorld is a guinea pig only — no tenant/INIT/repo hardcoding in programmes.

---

## Buzz UX contract (all roles — D3+)

Ops channel is for **human input and next steps**, not evidence dumps.

| Field | Rule |
|-------|------|
| **What** | ≤3 lines BLUF |
| **Evidence** | Link / path / PR only (`artefact_refs`) |
| **Next** | Exactly one: Lead reply tokens **or** “waiting on `{role}` / baton …” |
| **Tokens** | Only when a human gate is open |
| **Never** | Full walk trees, full KB diffs, raw forge JSON, multi-ask laundry lists |

Progress ticks while working (still-working); one short DONE rollup. Same DecisionCard / brief pattern as PM for any fork.

---

## Locked decisions

### Spine (unchanged)

| Topic | Choice |
|-------|--------|
| Product | ADH Team OS; RealWorld = guinea pig only |
| Package | `src/adh_agents/` only — no hermes runtime twin |
| Control plane | Orchestrator + work store + runner registry in `adh_agents/runtime` (**mandatory**) |
| Enabler | `BaseHermesAgent` = listen / baton / forge ACL / progress (not the router) |
| Agents | Embed control plane; role-scoped ops filter; one process per role |
| Programmes | Register on plane; under `adh_agents/programmes/{pm,pe,read,kb}/` |
| Redis work | `adh:agent:work:{tenant}:{role}:{work_id}` |
| Workers | `make adh-pm` / `adh-pe` / `adh-read` / `adh-kb` |
| Legacy | **Deleted** in #16 — HermesService facade, collaborator/session store, PendingMixin, pin/spawn OrchestratorService |
| Sequence | OS → V1 → V2 → D1–D5 depth → later hires |

### D3–D5 locks (2026-11-09)

| # | Topic | Choice |
|---|-------|--------|
| D3.1 | Walk model | **One repo per `read.walk` baton**; `repo_ref` in payload, resolved via **tenant context** (not `workspace_root` dump, not RealWorld literals) |
| D3.2 | First emit | PE may emit meta first (`tenant.meta_repo`); later fan-out follows Impact-Map — same baton shape |
| D3.3 | Rollup | **Deterministic** structured sketch → `artefact_refs`; Buzz = BLUF + link + next. **LLM consumes** rollup in PE (not in Read) |
| D3.4 | Codegraph | **Filesystem port only** this wave; keep `CodegraphPort` Protocol / degraded stub; MCP = later hire |
| D4.1 | Trigger | Emit `kb.enrich` on **post-merge success** (catalogue-aware / PM path) — not PE-at-attest, not silent side effect |
| D4.2 | Heads | OKF under `{tenant-meta}/knowledge/` only — `foundation/` · `stacks/` · `repos/` · `contracts/` — **no** `initiatives/` tree |
| D4.3 | Durability | Patch + **Buzz pointer** + forge **draft PR** under `knowledge/**` (KB forge ACL); Lead authorizes on forge/ops |
| D4.4 | Authoring | **A — stub scaffold + LLM fill** in the same writer (paths/sections deterministic; prose from LLM; OKF-validated) |
| D5.1 | Scope | Dup baton claim · baton/work **timeout reclaim** · wrong-stage authorize/resume · forge 422 → idempotent PR · authorize/forge errors **must not kill SSE** |
| D5.2 | Verify | Unit/contract tests for OS + **one** RealWorld guinea pig proof — guinea pig is not the design oracle |
| UX | Buzz | BLUF + artefact link + **single next step** (see contract above) |

### Agentic harness locks (2026-11-09)

Delivery copilot stays **catalogue-driven + conversational** (ADR 0001). No hardcoding, no regex as product SSOT.

| # | Topic | Choice |
|---|-------|--------|
| H1 | Next-step ownership | **LLM understand** maps Lead chat → catalogue `outcomes[]` / open-brief tokens. Catalogue still owns the graph — LLM does not invent a parallel workflow |
| H2 | No regex | **No regex / frozenset allowlists** for Lead intent **or** artefact parsing (PRD / Impact-Map / KB). Use understand + structured writers / LLM |
| H3 | Soft gates | **Always wait for Lead** on briefs. Forge / `authorization: explicit` never auto-run |
| H4 | KB content | Stub scaffold + LLM fill (**D4.4 A**) |
| H5 | Read vs PE | Read = deterministic sensor; PE/LLM interprets evidence for questions / recommend |
| H6 | LLM / understand down | Short Buzz **ask-back** (“say that again / pick from options”) — **no** regex fallback |

**Debt to retire while building D3–D5:** PE Q-cap regex parsers, phrase/token frozensets in pe_glue / lead_tokens used as SSOT, magic `repo="meta"` / blind `workspace_root` walks.

---

## Develop merge ledger

### Wave 0a (merged on `develop`)

| PR | Summary |
|----|---------|
| #6–#12 | PM on `BaseHermesAgent`; batons; TTL; resume; parallel sessions; `init_prefix` |
| #13–#14 | Network retry / stall-keep / resume live session |

**Wave 0a UAT (guinea pig):** RealWorld INIT-001 confirm → impact-map → authorize → draft PR → parked `pe.review` — **done**.

### Wave 0b

| PR | Summary |
|----|---------|
| #16 | Greenfield OS + minimal pe/read/kb; delete Hermes facade (#15 closed for branch rename) |

### Depth D1–D2

| PR | Summary |
|----|---------|
| #17 | Gate‑1 PE questions/attest + PM pe_glue / `prd_merge`; baton catch-up; forge ports |

---

## Layout (landed)

```text
src/adh_agents/
  runtime/           work_models, work_store, orchestrator, programme_runner, stall, catch_up
  baton/             models, redis_store
  catalogue/         resolve, navigator
  understanding/     understand_service
  collaboration/     brief_service
  execution/         dispatch_service
  surface/           buzz_poster
  programmes/pm|pe|read|kb/
  agents/            pm_agent, pe_agent, read_agent, kb_agent
  ports/             filesystem, codegraph stub
  forge_acl/
  base.py, settings.py

src/adh_pm_worker.py | adh_pe_worker.py | adh_read_worker.py | adh_kb_worker.py
```

---

## Next actions (in order)

### D3 — Read depth
1. Fix baton contract: `read.walk` payload `repo_ref` (+ reason); resolve checkout via tenant — remove PE/`walk` hardcode on magic `"meta"` / blind `workspace_root`.
2. Deepen filesystem port: structured sketch (entrypoints, caps) → artefact; Buzz UX contract.
3. Unit tests for resolve + rollup shape; guinea pig: walk visible as BLUF + next (PE continues / no Lead action unless error).

**Exit:** One-repo walk + structured rollup on Buzz without path dumps; ready for PE fan-out of N repos later.

### D4 — KB depth
1. Emit `kb.enrich` after successful `prd_merge` (catalogue-aware).
2. Writer: **OKF stub scaffold** (paths + required sections) → **LLM fill** from rollup/PRD refs → validate heads-only → local `knowledge/**`.
3. Forge ACL for `adh.kb` (paths under `knowledge/**` only); draft enrich PR; Buzz BLUF + **wait for Lead** authorize/hold.
4. Identity `adh.kb` on Buzz posts; no regex scraping of PRD into heads.

**Exit:** Head diff pointer on Buzz after enrich; durable proposal on meta forge; no initiative folders.

### D5 — Harden
1. Close gaps: dup claim, timeout reclaim, illegal authorize stage, forge 422 reuse, SSE survival on authorize/forge errors.
2. Route Lead replies via **understand → catalogue/brief** (H1–H2); on understand failure → ask-back (H6), not regex.
3. Contract tests for the matrix; short Buzz failure notices with **one** recovery next step.
4. Apply harden fixes anytime D3/D4 touch shared baton/forge/orchestrator code; focused D5 pass to close the bar.

**Exit:** OS survives redelivery, stall, and wrong-token without silent worker death; Lead path stays conversational.

### Order
**D3 → D4 → D5** (harden opportunistically while touching shared code).

---

## Success bar

| Gate | Bar |
|------|-----|
| 0b | One Orchestrator under `adh_agents/runtime`; legacy facades gone; `make adh-*` documented |
| V1 | PM live-proven on new work store |
| V2 | PE claims `pe.review`; read rollup |
| D1–D2 | Gate‑1 questions + attest + PM merge authorize |
| Gate‑1 UX | Decision paper (`*-hermes-gate1-brief.md`) mirrors PM promote Buying/Not buying; Buzz BLUF + artefact; auto `await_pm`; Lead forks `attest`/`new_round`/`hold`; purge temps (no archive) |
| D3 | Tenant-resolved one-repo walk; structured artefact; Buzz BLUF + next |
| D4 | KB head patch + Buzz pointer (+ enrich draft PR); heads-only policy |
| D5 | Dup/timeout/wrong-authorize/forge-idempotent/SSE-safe |
| Later | New roles plug into same Orchestrator + batons |

## Out of scope (unchanged)

- Stratum 20-repo production fan-out  
- Full QA docker programme  
- Codegraph MCP (port stub until later hire)  
- Reviving HermesService / dual session stores  
- TaskGraph as a separate hire (Impact-Map remains SSOT for repo DAG until then)
