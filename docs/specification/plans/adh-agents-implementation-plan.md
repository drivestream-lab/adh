# Implementation plan — ADH Agents Team OS

**Status:** Wave 0b greenfield spine in [PR #15](https://github.com/drivestream-lab/adh/pull/15); next = verify gates then programme depth.  
**ADR:** [0002](../adr/0002-adh-agents-team-os.md)  
**Product:** [adh-agents-team-os.md](../product/adh-agents-team-os.md)  
**As-built:** [implementation-status.md](../as-built/implementation-status.md)

This is the **work tracker**. Do not follow older “Hermes enabler + responsibility agents” phase lists that assumed a Hermes facade router.

---

## Work tracker (follow this)

```text
ADH Agents Team OS

0.  Product / ADR lock                              ✅
0a. PM on BaseHermesAgent + baton emit              ✅  PRs #6–#14
0b. Greenfield control plane + delete legacy        ✅  PR #15 (merge)
    - Orchestrator + work store + workers
    - PM programmes on plane
    - pe / read / kb hired (minimal)

── verify gate (block treating PE as “done”) ──
V1. PM live on new OS (RealWorld guinea pig)        ⬜  post-merge
V2. PE claims pe.review → read.walk                 ⬜

── depth (same OS — not new architecture) ──
D1. PE: Q caps (≤10 / ≤4 rounds), Buzz+PR, attest   ⬜
D2. PM glue: answer PE + prd_merge authorize        ⬜
D3. Read: real repo walks / richer ports            ⬜
D4. KB: actual knowledge/ head patches              ⬜
D5. Harden: dup batons, timeout, wrong authorize    ⬜

── later hires ──
dev / qa / iac / sre / obs + codegraph MCP          ⬜
```

**Rule:** architecture is closed after 0b. Remaining work deepens programmes on this spine.

---

## Develop merge ledger

### Wave 0a (merged on `develop`)

| PR | Summary |
|----|---------|
| #6–#12 | PM on `BaseHermesAgent`; batons; TTL; resume; parallel sessions; `init_prefix` |
| #13–#14 | Network retry / stall-keep / resume live session |

**Wave 0a UAT (guinea pig):** RealWorld INIT-001 confirm → impact-map → authorize → draft PR → parked `pe.review` — **done**.

### Wave 0b (PR #15)

Greenfield OS extraction + minimal pe/read/kb hire. Delete Hermes facade / runtime twin / pin OrchestratorService.

---

## Locked decisions

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
| Legacy | **Deleted** in #15 — HermesService facade, collaborator/session store, PendingMixin, pin/spawn OrchestratorService |
| Sequence | OS → **V1 PM verify** → **V2 PE handoff** → D1–D5 depth |

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

### V1 — PM on new OS
1. Merge PR #15; run `make adh-pm` (not `hermes-worker`).
2. Guinea pig: parallel sessions, ask-back, resume after restart, confirm / go ahead gates on RealWorld.
3. Confirm work keys under `adh:agent:work:…` (old `adh:hermes:session:` retired).

**Exit:** Lead can drive PM lane end-to-end on the new plane.

### V2 — PE handoff
1. `make adh-pe` + `make adh-read`.
2. After PM `open_draft_pr`, PE claims `pe.review`, emits `read.walk`, read posts rollup.

**Exit:** baton path draft → PE → read visible on Buzz (questions/attest still D1).

### D1–D5 — depth
Programme richness only — no second control plane. See tracker above.

---

## Success bar

| Gate | Bar |
|------|-----|
| 0b | One Orchestrator under `adh_agents/runtime`; legacy facades gone; `make adh-*` documented |
| V1 | PM live-proven on new work store |
| V2 | PE claims `pe.review`; read rollup |
| D1–D2 | Gate‑1 questions + attest + PM merge authorize |
| D4 | KB head diffs on Buzz after enrich |
| Later | New roles plug into same Orchestrator + batons |

## Out of scope (unchanged)

- Stratum 20-repo production fan-out  
- Full QA docker programme  
- Codegraph MCP (port stub until later hire)  
- Reviving HermesService / dual session stores  
