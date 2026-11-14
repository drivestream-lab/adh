# Implementation plan — Hire `adh.coder`

**Status:** Planning — branch `feature/coder-hire` from `develop` (post #40)  
**ADR:** [0005](../adr/0005-coder-hire.md)  
**Depends on:** E1 Dev board-seed fence; ADR [0003](../adr/0003-platform-agentic-extract-decide.md); ADR [0004](../adr/0004-hermes-behaviour-harness.md)  
**Product:** [adh-agents-team-os.md](../product/adh-agents-team-os.md)  
**YAML SSOT:** `prayog-skills/workflow.yaml` — nodes after `board-tickets-action`

**Intent:** After Dev seeds the board, **Coder** walks the wave chain (pre-implement → loop-spec → wave draft PR → human accept/signoff) against WorkManifest TASK* on Impact-Map Affected repos.

---

## Work tracker

```text
Coder hire

── C0 docs ──
C0 ADR 0005 + this plan + Team OS + as-built + tracker   🟨

── C1 spine ──
C1 CoderAgentSettings + CoderAgent + adh_coder_worker + make adh-coder   ⬜
C2 Dev → Coder baton on board-seeded; delete “Coder hire is later” coach  ⬜
C3 Coder programme: YAML walker from wave-in-progress-action            ⬜

── C2 forge + skills ──
C4 Dispatch pre-implement / loop-spec (commit_workspace)                ⬜
C5 wave-pr-action + board status updates; GateOpener on wave-acceptance/signoff  ⬜
C6 Fail-closed WorkManifest / ticket binding                            ⬜

── C3 behaviour ──
C7 hermes.coder.* packs (wave brief / accept recommend)                 ⬜
C8 Units + rg gates; no invented stages                                 ⬜

── C4 live ──
C9 Live: board-seeded INIT (god) wave → draft PR                        ⬜
C10 Live: human INIT — Lead plays wave-acceptance / signoff             ⬜
```

---

## Locked decisions (proposed)

| # | Lock |
|---|------|
| C.1 | Buzz role **`adh.coder`** (per-repo handles already seeded; default voice `adh.coder` + repo suffix when multi-repo) |
| C.2 | **YAML-only** after board seed: `wave-in-progress-action` → `pre-implement` → `loop-spec` → `wave-pr-action` → `wave-acceptance` → … → `wave-signoff` / complete |
| C.3 | **Dev does not code** — fence stays `board-seeded`; baton to Coder |
| C.4 | Collaboration floor remains **`#engg-<id>`** (board Issues are tickets, not a second chat home) |
| C.5 | Skills + forge from pin only; **no** invented programme stages |
| C.6 | GateOpener only on YAML **human-checkpoint** (`wave-acceptance`, `wave-signoff`, initiative-closure as applicable) |
| C.7 | God plays `recommend` on those gates (same AutonomyPolicy as Dev) |
| C.8 | Behaviour packs `hermes.coder.*` via PromptService only |
| C.9 | WorkManifest §9 + board ticket binding — fail closed if missing/stale |
| C.10 | One wave at a time per INIT until wave-complete (no parallel wave chaos in v1) |
| C.11 | Guinea pigs: reuse board-seeded RealWorld INIT (004 human preferred; one god) — wipe coder session only, not Dev artefacts |
| C.12 | Greenfield — delete “Coder hire is later” strings / stubs in the same PR as baton emit |

---

## Mental model

```text
PE → Dev (engg YAML → board-tickets-action)
        ↓ board-seeded + baton
     Coder (wave-* YAML → code + draft PR)
        ↓ wave-acceptance / wave-signoff (Lead or god)
     next wave or initiative-closure
```

---

## File-level plan

| Step | Scope |
|------|--------|
| **C0** | ADR 0005, this plan, Team OS Coder row, implementation-plan tracker, as-built |
| **C1** | `settings.CoderAgentSettings`, `agents/coder_agent.py`, `adh_coder_worker.py`, `scripts/run_adh_coder_worker.sh`, Makefile |
| **C2** | `programmes/dev` emit coder baton; `programmes/coder/` YAML walker |
| **C3** | Wire forge actions already used by Dev where YAML overlaps; wave-specific open_draft_pr / board status |
| **C4** | `src/prompts/hermes.coder.*`; thin runners |
| **C5** | Units: stage order, baton claim, WM fail-closed; live 004/god |

---

## Out of scope

- Verify agent / qa / iac / sre / obs  
- codegraph MCP as hire dependency  
- Stratum tenant onboard  
- Moving Dev fence past board seed  

---

## Acceptance

1. ADR 0005 accepted; locks C.1–C.12 confirmed.  
2. `make adh-coder` runs; claims Dev baton after board-seed.  
3. YAML wave chain progresses without invented stages.  
4. Live: at least one draft wave PR from a board-seeded INIT; human path plays acceptance brief.
