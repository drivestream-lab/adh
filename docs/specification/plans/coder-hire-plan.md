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
| C.10 | **Ready-set scheduling** — Coder(s) claim only waves whose `depends_on` waves are done; never invent parallelism beyond the WM DAG |
| C.11 | Guinea pigs: reuse board-seeded RealWorld INIT (004 human preferred; one god) — wipe coder session only, not Dev artefacts |
| C.12 | Greenfield — delete “Coder hire is later” strings / stubs in the same PR as baton emit |
| C.13 | **Swarm unit = repo-scoped coder handle** (`adh.coder.<repo>`) — derived from Affected/WM `repo`, never hardcoded repo lists |
| C.14 | **Within one repo / one wave:** walk TASK `depends_on` in order on **one** head branch; do not fan-out parallel TASK workers in v1 (WM defers `parallel_safe` / `shared_files`) |
| C.15 | Lead (or god) still owns **wave-acceptance / wave-signoff** per wave tip — swarm does not auto-merge |
| C.16 | **No hardcoding** — `integration_branch`, org, repos, INIT ids, board names come from tenant + WM + board + baton only |
| C.17 | **Parallel cap** — `max_parallel_coders` (settings/env, overridable) clips ready-set; per-repo lease = 1; never spawn “all Affected” blindly |
| C.18 | **Human-coder review bar (Hermes)** — after skills land tip: MDC/rules violations by severity (fix **P0/P1**, consciously defer **P2** with why); CAP/J coverage vs PRD+spec; fixtures/stimulus cover expectation; same packs drive **human** briefs and **god** `recommend` |

---

## Coder expectations (what “done with Dev” means)

After Dev we already have:

| Artefact | Role for Coder |
|----------|----------------|
| Merged **spec** slice(s) | Product contract per Affected repo |
| **Implementation-Plan** §9 WorkManifest | Immutable execution DAG (until coding-readiness lock) |
| **Board** EPIC + wave Issues | Long-term WM home — ticket ↔ `W{n}` ↔ `repo` ↔ TASK\* |

Coder does **not** re-plan. It **schedules and executes** ready work.

### Parallelism (swarm) — three layers

```text
INIT
 ├─ repo A ── adh.coder.repo-a ── ready waves (DAG) ── serial TASK* on one branch
 ├─ repo B ── adh.coder.repo-b ── ready waves (DAG) ── serial TASK* on one branch
 └─ …
```

1. **Across repos (swarm yes)** — If Impact-Map Affected has `api` + `web` and their waves do not depend on each other (no cross-wave / CTR gate forcing order), run **two coder workers** in parallel. Identity already seeded: `adh.coder.realworld-api`, etc. Stratum pressure = this layer.
2. **Across waves, same repo** — Only when wave `depends_on` is satisfied (e.g. W0 done → W1 ready). Same-repo waves usually chain (`W1 depends_on: [W0]`); do **not** parallelize those.
3. **Across TASK\* inside a wave** — DAG exists (`depends_on: [TASK-W0-01]`), but v1 stays **single worker, topological order** on one `feature/…-w{n}-…` branch. Prayog WM explicitly defers `parallel_safe` / file locks — overlapping `files[]` would thrash one PR tip.

### Ready-set (scheduler job)

At each hop, Coder computes:

```text
ready_waves = { W | all(d in W.depends_on are board-Done) and W not in progress }
claim = pick ready_waves filtered by this worker's repo handle
```

Buzz `#engg-<id>` stays the collaboration floor; board columns are the swarm scoreboard.

### What Coder owes Lead per wave

- Pre-implement checklist on head (clean sync of `integration_branch`)  
- TASK\* execution + proofs → `Wave-Execution-{INIT}-W{n}.md`  
- Draft wave PR (`wave-pr-action`, base = `integration_branch`)  
- **Human-shaped review brief** for `wave-acceptance` / signoff (below)  
- No merge without `wave-signoff`

### Hermes value — mimic a human developer (collaborative human + god)

Skills (`loop-spec` / `pre-implement`) are the hands. **Hermes `hermes.coder.*`** is how *you* review what those hands did before accepting the tip — same card in **human** (you reply tokens) and **god** (GateOpener plays `recommend`).

```text
skill tip (code + fixtures + Wave-Execution)
        ↓
hermes.coder.review / wave-acceptance brief
  1) MDC / rules scan → severity bucket
  2) Fix or demand fix: P0, P1
  3) P2: explicit leave-with-why (not silent ignore)
  4) CAP-* / J-* implemented vs PRD + spec slice
  5) Fixtures / live_verify cover those CAP/J (stimulus+probes) — gaps called out
  6) recommend ∈ reply_tokens + locking / not_locking / revise_if
        ↓
Lead (human) or god plays token → accept / findings / hold
```

| Human habit | Pack behaviour |
|-------------|----------------|
| Read diff vs `.cursor/rules` / MDC | List violations with **P0 / P1 / P2** |
| Fix blockers before ask-for-review | P0/P1 → `findings` / hold until tip patched (or skill re-entry) |
| “Why I left the lint nits” | P2 → `not_locking` + why deferred this wave |
| Trace CAP/J to PRD/spec | Coverage matrix in brief (covered / missing / N/A) |
| Do fixtures actually prove the story? | Fixture paths ↔ CAP/J ↔ REQ; call thin or missing packs |
| Pair with Lead | Buzz helpful-army brief; god uses same `recommend` |

**Not Hermes:** inventing TASK order, moving board columns, opening the PR, running live smoke and claiming look-at success (skill handoff already forbids that — human/god prove at acceptance).

---

## Mental model

```text
PE → Dev (engg YAML → board-tickets-action)
        ↓ board-seeded + baton(s) per Affected repo
     Coder swarm (adh.coder.<repo>) — ready waves only
        ↓ each wave: pre-implement → loop-spec → draft PR
        ↓ wave-acceptance / wave-signoff (Lead or god)
     next ready wave(s) or initiative-closure
```

---

## File-level plan

| Step | Scope |
|------|--------|
| **C0** | ADR 0005, this plan, Team OS Coder row, implementation-plan tracker, as-built |
| **C1** | `settings.CoderAgentSettings`, `agents/coder_agent.py`, `adh_coder_worker.py`, `scripts/run_adh_coder_worker.sh`, Makefile |
| **C2** | `programmes/dev` emit coder baton; `programmes/coder/` YAML walker |
| **C3** | Wire forge actions already used by Dev where YAML overlaps; wave-specific open_draft_pr / board status |
| **C4** | `src/prompts/hermes.coder.*` (review / wave-acceptance / signoff) — MDC severity + CAP/J + fixtures; thin runners; human+god same packs |
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
