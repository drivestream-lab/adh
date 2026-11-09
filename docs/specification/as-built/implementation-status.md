# As-built — ADH Agents Team OS

**Tracker SSOT:** [adh-agents-implementation-plan.md](../plans/adh-agents-implementation-plan.md)

## Spine

| Item | Status |
|------|--------|
| 0 / 0a — ADR + PM on `BaseHermesAgent` + baton emit | ✅ `develop` (#6–#14); INIT-001 guinea pig done |
| 0b — Greenfield control plane + delete legacy | ✅ [PR #16](https://github.com/drivestream-lab/adh/pull/16) |
| V1 — PM live on new OS | ✅ RealWorld INIT-001 ask-back/resume/gates/authorize |
| V2 — PE claims `pe.review` → read.walk | ✅ baton catch-up + read rollup |
| D1 — PE Q caps, Buzz+PR, attest + `impact-map-lgtm` | ✅ [PR #17](https://github.com/drivestream-lab/adh/pull/17); guinea pig PR #2 |
| D2 — PM ack PE + `prd_merge` authorize | ✅ PR #17; meta PR #2 merged |
| D3 — Read: one-repo walk / structured rollup | ⬜ locks in plan |
| D4 — KB: `knowledge/` head patches + Buzz pointer | ⬜ locks in plan |
| D5 — Harden: dup / timeout / authorize / forge / SSE | ⬜ locks in plan |

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
