# Implementation plan — Hermes behaviour harness

**Status:** Implementing — **single PR** (`feature/hermes-behaviour-harness`); live verify INIT-003/004 after merge  
**ADR:** [0004](../adr/0004-hermes-behaviour-harness.md)  
**Depends on:** ADR [0003](../adr/0003-platform-agentic-extract-decide.md) (extract/allow-list stays); E1 Dev YAML walker already on `develop`  
**Product:** [adh-agents-team-os.md](../product/adh-agents-team-os.md)  
**KB heads:** [adh-kb-heads.md](../references/adh-kb-heads.md)  
**As-built:** update row when wave starts  

**Intent:** Codify **human behaviour** for each hire (PM/PE/Dev/KB) as Hermes prompt packs so judgment can evolve like a human does — with knowledge closing the loop. Skills remain the delivery harness; prompts are the behaviour harness **on top**.

**No legacy / dual paths / dead code.** Greenfield replacements **delete** inline judgment prompts, unused helpers, and obsolete tests **in the same PR**. No stubs, no “kept for reference,” no compatibility shims. ADH is the product; RealWorld guinea pigs = **INIT-REALWORLD-003** / **INIT-REALWORLD-004** only for this train.

---

## Work tracker

```text
Hermes behaviour harness

── planning ──
B0 ADR 0004 + this plan + Team OS section + as-built stub     🟨  in review

── wave B1 (greenfield Dev packs — delete all dead inline) ──
B1 Prompt packs hermes.dev.* + thin debate/decide runners     ⬜
B2 DELETE inline prompt bodies + dead helpers/tests; PromptService-only  ⬜
B3 Units + prompt contract; rg clean (zero hits)              ⬜
B4 Live verify Dev **INIT-003 god** / **INIT-004 human**      ⬜

── wave B2 (PE packs — same guinea pigs) ──
B5 hermes.pe.* + PE programme wired; DELETE heuristic judge dead code  ✅
B6 Live verify PE on **003 god** / **004 human** (product→engg as needed)  ✅
   evidence: /tmp/adh-hermes-pe-b2-live/{init-realworld-003,init-realworld-004}/
   (product fence already closed — live PromptService.complete on Impact-Maps;
    gate1.recommend ∈ await_pm|new_round|hold|attest; impact.challenge ∈ proceed|revise_map|hold)

── wave B3 (knowledge loop Mode A) ──
B7 Inject OKF head excerpts into hop variables                ⬜
B8 hermes.kb.learning.* shape; learning-extract → inject      ⬜
B9 Guinea pig **003/004**: post-fence learning visible on next hop  ⬜

── later ──
Mode B: learning → Lead-gated hermes.*.yaml PR drafts         ⬜
Coder hire behaviour packs                                    → see [coder-hire-plan.md](coder-hire-plan.md)
Agentic Lead classify (ADR 0003 hole)                         ⬜
```

---

## Locked decisions (proposed — confirm before code)

| # | Lock |
|---|------|
| B.1 | **Two harnesses:** delivery = `workflow.yaml` + prayog skills + forge; behaviour = `src/prompts/hermes.{role}.*` via `PromptService` only |
| B.2 | **Greenfield / zero dead code:** delete inline judgment/decide/debate prompt strings, unused helpers, and obsolete tests **in the same PR**; no fallback dual path; no stubs “for later” |
| B.3 | **PM packs remain gold** — do not rewrite PM unless a pack violates PromptService contract; extend by addition |
| B.4 | **Character vs hop:** each role has shared character defaults + per-purpose hop overlays (variables: `purpose`, `evidence`, `reply_tokens`, `kb_excerpt`) |
| B.5 | **Extract stays code** (ADR 0003). Runners only render+complete+extract; programmes stay thin |
| B.6 | **Evolution Mode A this train** — KB head excerpts injected into prompt vars; prompts themselves change only via normal PRs |
| B.7 | **Mode B later** — learning-extract may open a draft PR against `src/prompts/`; Lead merges; never auto-merge (Mode C refused) |
| B.8 | **Skills prompts stay under prayog** — artefact generation is not moved into Hermes packs |
| B.9 | **Fail-closed:** missing template id → hard error (no silent inline recreate) |
| B.10 | **No tenant/INIT hardcoding** in packs or runners; guinea pigs are RealWorld **003/004** only for verify |
| B.11 | **Dead-code delete list + `rg` gates** are mandatory merge exit criteria (B1/B2); PR fails review if any listed symbol remains |
| B.12 | **Verify slate:** **INIT-REALWORLD-003** (god) + **INIT-REALWORLD-004** (human) — Dev in B1; PE on same INITs in B2 |

---

## Mental model (normative)

```text
Lead ↔ Buzz
        ↑
  Hermes role prompt packs     ← behaviour (comprehend / ask / review / recommend)
        ↑ variables include
  OKF knowledge heads          ← evolved memory (Mode A inject; Mode B prompt PRs later)
        ↑
  workflow.yaml GateOpener     ← when to stop for judgment / authorize
        ↑
  prayog skills + forge        ← delivery artefacts / GitHub
```

Behaviour packs answer: *what would this hire ask / lock / recommend?*  
Skills answer: *produce the next artefact.*

---

## Delete (no stubs / no dead code) — merge exit criteria

### B1 (Dev) — must be gone

| Remove | Reason |
|--------|--------|
| `_pass_prompt` and all inline system/user bodies in `programmes/dev/debate.py` | Behaviour → `hermes.dev.debate.pass` |
| Hard-coded `litellm.complete("You are adh.dev…")` (and siblings) in debate | Same |
| Inline prompt joins in `runtime/agentic_decide.py` | → `hermes.dev.decide.*` |
| Any “if prompt missing, build string” / try-except recreate shim | Dual path |
| Duplicate role-local decide helpers that embed prompts | One platform runner |
| Unit tests that assert old inline prompt substrings | Rewrite or delete |
| Docs that describe inline debate as SSOT | Point to packs + ADR 0004 |

### B2 (PE) — must be gone

| Remove | Reason |
|--------|--------|
| Heuristic / hard-coded “recommended” judgment prose that duplicates pack behaviour in `pe/questions.py` / review paths **once packs own that hop** | Dead parallel behaviour |
| Any PE inline `litellm.complete("…")` judgment strings found in-wave | → `hermes.pe.*` |
| Orphan PE helpers left unused after PromptService wire | No dead code |

**Keep / thin-wrap only:** `run_dev_debate` / `decide_*` **names** if they solely call `PromptService` + `agentic_extract`; GateOpener; forge ACL; skill dispatch; PM YAML packs; PE card **schema** types.

**PR checklist (required):** paste empty `rg` gate output in PR body; reviewer rejects if any listed symbol remains.

---

## Pack inventory (target)

### Already live (PM) — reference only

| id | Purpose |
|----|---------|
| `hermes.pm.brief` | PO brief card |
| `hermes.pm.outline` | Outline / bind |
| `hermes.pm.validate.card` | Validate |
| `hermes.pm.promote.judge` | Promote judgment |
| `hermes.pm.postpm.judge` | Post-PM judgment |
| `hermes.pm.skill.invoke` | Skill invoke framing |
| `hermes.copy.*` | Status/artefact copy |

### B1 — Dev (new)

| id | Purpose | Replaces |
|----|---------|----------|
| `hermes.dev.character` | Shared Dev voice / review bar (optional include via defaults) | — |
| `hermes.dev.debate.pass` | Multi-pass debate body (purpose, tokens, prior, evidence, kb_excerpt) | `debate._pass_prompt` |
| `hermes.dev.decide.reply` | Single-shot recommend ∈ reply_tokens | `decide_reply_token` inline |
| `hermes.dev.decide.outcome` | Catalogue outcome ∈ YAML outcomes | `decide_catalogue_outcome` inline |

Hop overlays are **variables** (`purpose=coding-readiness|technical-review-approval|…`), not one YAML file per hop unless a hop needs a distinct response model.

### B2 — PE (new)

| id | Purpose |
|----|---------|
| `hermes.pe.impact.challenge` | Questions / recommend on impact-map before Gate 1 |
| `hermes.pe.gate1.recommend` | Attest / findings / hold framing |
| `hermes.pe.grounding` | Codebase-map / product-question challenge |

### B3 — KB (new)

| id | Purpose |
|----|---------|
| `hermes.kb.learning.harvest` | What to extract after fence / findings |
| `hermes.kb.inject.summarize` | Compress head → `kb_excerpt` for hop vars (optional) |

---

## File-level plan

Branch from current `develop` (post #30/#31). **Docs-first commit, then greenfield code.**

```text
B0 docs (ADR+plan+Team OS+as-built)
  → B1 hermes.dev YAML + PromptService runners + DELETE all dead inline
  → B1 tests + prompt_contract + empty rg gates
  → B1 live INIT-003 god / INIT-004 human
  → B2 hermes.pe + PE wire + DELETE PE dead heuristics + 003/004
  → B3 KB inject Mode A + learning harvest on 003/004
```

### B0 — Docs

| File | Change |
|------|--------|
| `docs/specification/adr/0004-hermes-behaviour-harness.md` | This ADR (proposed → accepted when locks confirmed) |
| `docs/specification/plans/hermes-behaviour-harness-plan.md` | This plan SSOT |
| `docs/specification/plans/adh-agents-implementation-plan.md` | Tracker row: behaviour harness wave; pointer here |
| `docs/specification/product/adh-agents-team-os.md` | Section: behaviour harness vs delivery harness |
| `docs/specification/as-built/implementation-status.md` | Row B0–B3 |
| `docs/specification/adr/README.md` | Link 0004 |
| `docs/specification/README.md` | Link plan + ADR |

### B1 — Dev greenfield packs

| File | Change |
|------|--------|
| `src/prompts/hermes.dev.debate.pass.yaml` | **NEW** — debate pass template + response model (labeled lines or JSON per PromptService norms) |
| `src/prompts/hermes.dev.decide.reply.yaml` | **NEW** |
| `src/prompts/hermes.dev.decide.outcome.yaml` | **NEW** |
| `src/models/prompt_models.py` | Response models if new schemas needed (prefer reuse recommend/outcome models) |
| `src/adh_agents/programmes/dev/debate.py` | **Rewrite thin:** PromptService.complete(`hermes.dev.debate.pass`) → extract; **delete** `_pass_prompt` body |
| `src/adh_agents/runtime/agentic_decide.py` | **Rewrite thin:** PromptService only; **delete** inline prompt joins |
| `src/adh_agents/programmes/dev/programme.py` | Pass `kb_excerpt=""` (stub until B3); no new inline prompts |
| `tests/unit/test_dev_debate_prompts.py` | **NEW** — template loads; complete mocked; extract allow-list |
| `tests/unit/test_agentic_decide.py` | Update: no inline; template ids |
| `prayog-skills/tests/fixtures/prompt_inventory.json` + contract | Include new hermes.dev ids if inventory covers `src/prompts` |

**rg gates (CI or local exit):**

```text
# must be empty after B1
rg -n '_pass_prompt|You are adh\.dev debating|Decide one catalogue outcome' src/adh_agents
rg -n 'litellm\.complete\(\s*\"' src/adh_agents/programmes/dev src/adh_agents/runtime/agentic_decide.py
```

### B2 — PE packs

| File | Change |
|------|--------|
| `src/prompts/hermes.pe.*.yaml` | **NEW** per inventory |
| `src/adh_agents/programmes/pe/**` | Wire judgment hops through PromptService; delete any inline judge strings found |
| Units + live **003 god / 004 human** | |

### B3 — Knowledge loop Mode A

| File | Change |
|------|--------|
| `src/adh_agents/programmes/dev/programme.py` (and PE) | Resolve OKF excerpt for initiative’s impacted repos/stacks → `kb_excerpt` var |
| `src/prompts/hermes.kb.learning.harvest.yaml` | **NEW** |
| `programmes/kb/**` or learning-extract skill glue | After fence/findings: harvest → head patch (existing KB land path) |
| Test | Next hop render includes non-empty `kb_excerpt` when head exists |

---

## Evolution loop (normative)

```text
Initiative fence / findings
  → hermes.kb.learning.harvest (+ skill/land)
  → OKF knowledge/ head patch (git)
  → next hop: read heads → kb_excerpt → hermes.{role}.* variables
  → better questions / locking / recommend
  → (later Mode B) optional PR editing hermes.*.yaml — Lead merges
```

KB does **not** become initiative folders. Heads stay as [adh-kb-heads.md](../references/adh-kb-heads.md).

---

## Stratum Hermes dry-run slate (no tenant onboard)

Distinct from RealWorld **live** guinea pigs **INIT-003 / INIT-004**. Pressure-tests the
same two harnesses against **Stratum-shaped** artefacts (multi-table Impact-Maps,
`Sandvik-Common/…` full names, edge / platform-core / HITL / IaC) **without**
`tenants.yaml`, roles install, Buzz army, or forge.

| Layer | What | When |
|-------|------|------|
| **L1** pack render | Every `hermes.{pm,pe,dev,kb}.*` hop × scenario via PromptService | CI — `tests/unit/test_hermes_stratum_dryrun.py` |
| **L2** delivery parse | `parse_affected_repos` Affected-only + Spec path/branch goldens | CI — same file |
| **L3** live complete | Opt-in model complete → `/tmp/adh-hermes-stratum-dryrun/` | Lead laptop only |

Fixtures + index: [`tests/fixtures/hermes/stratum/`](../../../tests/fixtures/hermes/stratum/)
(`scenarios.yaml`). Runner:

```bash
.venv/bin/python -m tests.verify.hermes_stratum_dryrun
.venv/bin/python -m tests.verify.hermes_stratum_dryrun --live --scenarios edge-008,core-002
```

Scenarios: `edge-008`, `core-002`, `hitl-001`, `iac-004`. No `src/` changes required for the dry-run bank.

---

## Out of scope

- Mode C auto-merge of prompt packs  
- Moving prayog skill templates into `src/prompts/`  
- Coder hire implementation (tracked in [coder-hire-plan.md](coder-hire-plan.md) / ADR 0005 — packs only referenced from here)  
- verify / qa hires  
- Replacing forge/label/Gate 2 mechanical rules with prompts  
- Rewriting E1 YAML walker  
- Stratum tenant registration / ORCH cutover (dry-run uses fixtures only)  


---

## Acceptance (wave B1)

1. ADR 0004 accepted; plan locks confirmed.  
2. `src/prompts/hermes.dev.*` exist and load via PromptService.  
3. `rg` delete gates clean — no inline debate/decide prompt bodies.  
4. Unit tests green; prompt inventory/contract updated.  
5. Live: Dev **INIT-REALWORLD-003 (god)** and **INIT-REALWORLD-004 (human)** complete coding-readiness debate using packs only (evidence: Buzz BLUF + logs show template ids).  
6. **Zero dead code:** delete-list items gone; `rg` gates empty in PR.

---

## Open confirmations (Lead)

Before B1 code:

1. Accept locks **B.1–B.12** (or amend).  
2. Confirm **Mode A first** (inject-only); Mode B deferred.  
3. Confirm **Dev wave before PE** (B1→B2) vs parallel.  
4. Accept ADR 0004 status → Accepted.  
5. Guinea pigs locked: **003 god / 004 human** (not 001/002/007/008).
