# As-built — ADH Agents Team OS

**Tracker SSOT:** [adh-agents-implementation-plan.md](../plans/adh-agents-implementation-plan.md)

## Spine

| Item | Status |
|------|--------|
| 0 / 0a — ADR + PM on `BaseHermesAgent` + baton emit | ✅ `develop` (#6–#14); INIT-001 guinea pig done |
| 0b — Greenfield control plane + delete legacy | ✅ [PR #15](https://github.com/drivestream-lab/adh/pull/15) |
| V1 — PM live on new OS | ⬜ post-merge |
| V2 — PE claims `pe.review` → read.walk | ⬜ |
| D1–D5 — PE/PM/read/kb depth + harden | ⬜ |

## Landed (0b)

| Capability | Status |
|------------|--------|
| `adh_agents/runtime` Orchestrator + work store (`adh:agent:work:…`) | landed |
| PM programmes under `adh_agents/programmes/pm/` | landed |
| `PMAgent` embeds Orchestrator (no HermesService facade) | landed |
| `make adh-pm` / `adh-pe` / `adh-read` / `adh-kb` | landed |
| pe / read / kb hired (minimal baton claim + fan-out) | landed |
| Hermes runtime twin / PendingMixin / pin OrchestratorService | deleted |

## Commands

```bash
make adh-pm    # PMAgent + control plane
make adh-pe    # PEAgent claims pe.review
make adh-read  # ReadAgent claims read.walk
make adh-kb    # KbAgent claims kb.enrich

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest tests/unit/ -q
```

## Retired wording

Do not track work as “Hermes enabler phases” or `make hermes-worker`. Enabler = `BaseHermesAgent`; router = Orchestrator; workers = `adh_*`.
