# As-built — ADH Agents Team OS

## Wave 0a (live-proven on guinea pig)

| Capability | Status |
|------------|--------|
| Validate / post-PM / impact-map / `open_draft_pr` | **live-proven** (RealWorld INIT-001) |
| `pe.review` baton emit after draft PR | live (consumers = Wave 0b) |
| Parallel sessions / ask-back / TTL / resume / network retry | proven on PM; now OS runtime |

## Wave 0b (this train — greenfield)

| Capability | Status |
|------------|--------|
| Control plane `adh_agents/runtime` (Orchestrator, work store, stall, catch_up) | **landed** |
| Work Redis keys `adh:agent:work:{tenant}:{role}:{work_id}` | **landed** |
| PM programmes under `adh_agents/programmes/pm/` | **landed** |
| `PMAgent` embeds Orchestrator (no `HermesService` facade) | **landed** |
| `make adh-pm` / `adh-pe` / `adh-read` / `adh-kb` | **landed** |
| `adh.read` / `adh.pe` / `adh.kb` hire (baton claim programmes) | **landed** (minimal fan-out) |
| Delete hermes runtime twin / PendingMixin / pin OrchestratorService API | **landed** |
| PM verify on new OS (live guinea pig) | **next** after worker restart |
| Full PE Q caps / attest / PM merge glue / KB head patches | incremental on same plane |

## Verify

```bash
make adh-pm    # PMAgent + control plane
make adh-pe    # PEAgent claims pe.review
make adh-read  # ReadAgent claims read.walk
make adh-kb    # KbAgent claims kb.enrich

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest tests/unit/ -q

# rg gate (agent path — must be empty of deleted facades):
# HermesCollaboratorService|HermesSessionStoreService|class HermesService|PendingMixin
```
