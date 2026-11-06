# Implementation plan — ADH Agents Team OS

**Status:** Wave 0a on `develop` (PRs #6–#12 merged 2026-11-06). Wave 0b not started.  
**ADR:** [0002](../adr/0002-adh-agents-team-os.md)  
**Product:** [adh-agents-team-os.md](../product/adh-agents-team-os.md)

## Develop merge ledger (Wave 0a)

| PR | Summary |
|----|---------|
| #6 | `BaseHermesAgent` + `PMAgent` cutover; batons; memory-room retire; `pe.review` emit after draft PR |
| #7 | Buzz SSE parse hotfix |
| #8 | Ops-only Buzz room list |
| #9 | Session TTL ≥ 2 days for Lead gates |
| #10 | Resume after TTL (artefact reopen) |
| #11 | Per-(tenant, initiative) sessions; ask-back when ambiguous; parallel outlines |
| #12 | Initiative identity from `tenant.init_prefix` only |

**UAT remaining:** RealWorld INIT-001 pressure-test (confirm → impact-map → authorize → parked `pe.review`).

## Locked decisions

| Topic | Choice |
|-------|--------|
| Package | `src/adh_agents/` |
| Processes | One process per role |
| Baton store | Redis (state/idempotency) + Buzz (talk/trigger) |
| Codegraph | Tool port on **read** agent; degraded filesystem now; MCP later |
| KB | Heads only; **kb** agent writes via Buzz |
| PM lane | Leverage; emit/consume batons only — no full rewrite |
| Greenfield | Team OS + pe/read/kb; not entire ADH |

## Architecture

```text
#tenant-ops Buzz
  humans + adh.pm | adh.pe | adh.read | adh.kb | (later …)
           │
    src/adh_agents/  (baton · roster · worker · ports · forge_acl)
           │
    role programmes + catalogue navigator + forge (ACL) + Cursor tools
```

### Baton / rollup (versioned)

- **Baton:** `{version, id, role, tenant, room, stage, initiative?, pr_url?, repo?, sha?, payload, idempotency_key}`
- **Rollup:** `{version, baton_id, role, status, summary, artifacts[], questions?, tools_used[], error?}`
- **Idempotency key (example):** `{role}:{tenant}:{pr|init}:{repo?}:{sha?}:{stage}`
- Redis key: `adh:baton:{tenant}:{idempotency_key}` → claimed|running|done|expired

### Package layout

```text
src/adh_agents/
  __init__.py
  baton/          models, redis_store, claim
  roster/         enabled roles per tenant/room
  worker/         base listen → claim → run → rollup
  ports/          codegraph.py (stub), filesystem.py, docker.py (stub later)
  forge_acl/      allowed forge actions per role

src/hermes_pm_worker.py      # existing
src/hermes_pe_worker.py      # new
src/hermes_read_worker.py    # new
src/hermes_kb_worker.py      # new
# alternative: python -m src.adh_agents.worker --role pe  (still one process per role)
```

## Phases

### Phase 0 — Plan docs (this PR)

- [x] ADR 0002  
- [x] Product + KB heads + this plan  
- [x] As-built / README index updates  

### Phase 1 — `adh_agents` kernel

| Deliverable | Notes |
|-------------|--------|
| Baton/Rollup models | Pydantic; version field |
| Redis baton store | claim / complete / expire |
| Base worker loop | Buzz subscribe filtered by role; post rollups |
| Roster settings | `ADH_AGENT_ROLE`, enable flags |
| Unit tests | idempotency, double-claim, expire |

**Exit:** tests only — fake baton claim/complete without PE business logic.

### Phase 2 — `adh.read`

| Deliverable | Notes |
|-------------|--------|
| Code reader programme | WalkRequest → tools → WalkRollup |
| Filesystem/grep port | Live |
| CodegraphPort | Stub / degraded |
| Prompt | `hermes.read.walk.yaml` |
| Worker | `hermes_read_worker` |

**Exit:** Buzz walk baton for `realworld-api` → rollup in `#realworld-ops`.

### Phase 3 — `adh.pe`

| Deliverable | Notes |
|-------------|--------|
| PE programme | `prd-impact-acceptance` coordinator |
| Fan-out | Impact-Map affected repos → read batons (parallel) |
| Wait/timeout | Missing reader policy |
| Caps | ≤10 questions, ≤4 PE↔PM rounds |
| Surfaces | Buzz briefs + PR comment mirror |
| Attest | ready + Approve(attestation) + `impact-map-lgtm` (ACL) |
| Handoff | Merge baton / Buzz ping to PM |

**Exit:** Dry-run on meta PR #1 through questions; attest behind flag.

### Phase 4 — PM glue (minimal)

| Deliverable | Notes |
|-------------|--------|
| After `open_draft_pr` | Emit PE review baton |
| PM answers | Judgment / baton replies to PE questions |
| `prd_merge` | Explicit authorize → merge forge |

**Exit:** INIT-001 controlled path draft→PE→read→Qs→attest→merge.

### Phase 5 — `adh.kb`

| Deliverable | Notes |
|-------------|--------|
| Seed | `realworld-meta/knowledge/` heads |
| KB programme | Enrich baton → patch heads only |
| Trigger | PE/PM after merge |

**Exit:** Head diffs posted on Buzz after merge enrich.

### Phase 6 — PoC harden

- Pressure: duplicate batons, reader timeout, wrong “go ahead”, reader cannot attest  
- As-built status → live-proven Gate‑1 swarm  

### Phase 7+ (same OS, later PRs)

- Dependency-DAG scheduler for `dev.*`  
- `qa` docker verify → GitHub check  
- `iac` / `sre` / `obs`  
- Codegraph MCP adapter  

## Leverage vs greenfield

| Leverage | Greenfield |
|----------|------------|
| Buzz, tenants, Redis, DI | `src/adh_agents/` |
| Catalogue, navigator, briefs | pe/read/kb programmes + workers |
| Forge + GitHub App (extend) | Baton store + forge ACL |
| Cursor / skill runner / workspace | Tool ports |
| PM authoring + meta-pm | Emit/consume batons only |

**Do not build on:** pending-key sprawl for swarm, in-process PE digests, INIT KB folders.

## File checklist (Phases 1–5)

| Area | Paths |
|------|--------|
| OS | `src/adh_agents/**` |
| Tests | `tests/unit/test_adh_agents_*.py` |
| Read | `…/programmes/code_reader_programme.py`, `hermes_read_worker.py`, `prompts/hermes.read.walk.yaml` |
| PE | `…/programmes/pe_programme.py`, `hermes_pe_worker.py`, `prompts/hermes.pe.*.yaml` |
| KB | `…/programmes/kb_programme.py`, `hermes_kb_worker.py`, meta `knowledge/**` |
| PM glue | `meta_pm_programme.py`, orchestrator baton emit |
| Forge | `github_app_service.py` ready/review/labels; ACL wrapper |
| Config | `hermes_settings` / new `adh_agents_settings`, `.env.example`, `Makefile` |

## Success bar (RealWorld PoC)

1. Kernel batons green in CI  
2. Parallel read walks api+web on PR #1  
3. PE question wave + caps  
4. Attest + PM merge (controlled)  
5. KB head patches  
6. Codegraph still a hole  

## Out of scope for first merge train

- Stratum 20-repo production fan-out  
- Full QA docker programme  
- Rewriting `HermesService` mixins (optional cleanup later)  
