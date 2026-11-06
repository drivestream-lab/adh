# Implementation plan — ADH Agents Team OS

**Status:** Wave 0b greenfield control plane — single PR from `develop` (`feat/adh-agents-team-os-greenfield`).  
**ADR:** [0002](../adr/0002-adh-agents-team-os.md)  
**Product:** [adh-agents-team-os.md](../product/adh-agents-team-os.md)

## Develop merge ledger

### Wave 0a (merged)

| PR | Summary |
|----|---------|
| #6–#12 | PM on `BaseHermesAgent`; batons; TTL; resume; parallel sessions; `init_prefix` |
| #13–#14 | Network retry / stall-keep / resume live session |

**Wave 0a UAT:** RealWorld INIT-001 confirm → impact-map → authorize → draft PR → parked `pe.review` — **done** (guinea pig).

### Wave 0b (this train)

Greenfield OS extraction + hire read/pe/kb. Verify **PM on new OS** before treating PE handoff as done.

## Locked decisions

| Topic | Choice |
|-------|--------|
| Product | ADH Team OS; RealWorld = guinea pig only |
| Package | `src/adh_agents/` only — no hermes runtime twin |
| Control plane | Orchestrator + work store + runner registry in `adh_agents/runtime` |
| Agents | Embed control plane; role-scoped ops filter |
| Programmes | Register on plane; PM/PE/read/kb under `adh_agents/programmes/` |
| Redis work | `adh:agent:work:{tenant}:{role}:{work_id}` |
| Workers | `make adh-pm` / `adh-pe` / `adh-read` / `adh-kb` |
| Legacy | **Delete** — HermesService facade, HermesCollaborator, session store, PendingMixin, unused hermes router/store, pin/spawn OrchestratorService |
| Sequence | OS → verify PM → read → PE handoff → PM merge glue → kb |

## Target layout

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

src/adh_pm_worker.py
src/adh_pe_worker.py
src/adh_read_worker.py
src/adh_kb_worker.py
```

## Delete list (same PR — no shims)

- `business_services/hermes/runtime/*` (orchestrator, session_store, navigator → moved)
- `business_services/hermes_service.py`
- `business_services/hermes/pending.py`
- Emptied `business_services/hermes/**` after moves
- `models/hermes/session_models.py` (replaced by `runtime/work_models.py`)
- Legacy `business_services/orchestrator_service.py` + `/orchestrator` API + tests if unused
- `hermes_worker.py` / `make hermes-worker` (replaced by `adh_*`)
- `hermes_router` / `hermes_store_service` when nothing remains that needs them

## Phases (single PR)

| Phase | Exit |
|-------|------|
| A Docs | ADR/plan/product/as-built locked |
| B Runtime | Unit tests: parallel work, ask-back, resume, stop |
| C Move + PMAgent + make + DELETE legacy | `rg` clean; `make adh-pm` runs |
| D Baton claim/expire + role filter | Baton tests green |
| Verify PM | Guinea-pig pressure on new OS |
| E read → pe handoff → PM glue → kb | Hired on same plane |
| Tests / PR | `test_adh_*`; open PR to develop |

## Success bar (product)

1. One Orchestrator implementation under `adh_agents/runtime`  
2. PM verified on new OS (parallel / resume / gates)  
3. PE claims `pe.review`; read rollups; PM merge authorize  
4. No HermesCollaborator / HermesService / dual session store left  
5. `make adh-pm` / `adh-pe` / `adh-read` / `adh-kb` documented  

## Out of scope

- Stratum 20-repo production fan-out  
- Full QA docker programme  
- Codegraph MCP (port stub only)  
