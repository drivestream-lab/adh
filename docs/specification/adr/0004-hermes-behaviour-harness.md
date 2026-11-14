# ADR 0004 — Hermes behaviour harness (role prompt packs + knowledge loop)

- **Status:** Accepted — single-PR greenfield behaviour harness (`feature/hermes-behaviour-harness`)
- **Date:** 2026-11-12
- **Context:** Skills + `workflow.yaml` are the **delivery harness** (artefacts, forge, predicates). Hired roles (PM, PE, Dev, KB, …) must also **mimic Lead/eng human behaviour** — the questions asked, how ADRs/TDD/impact are reviewed, how recommends are framed. That behaviour must be **codified, reviewable, and evolvable** (same way a human improves). Today only PM has first-class Hermes YAML packs under `src/prompts/`; Dev/PE judgment uses **inline** strings in `debate.py` / `agentic_decide.py`. That is debt: behaviour is not PR-diffable, not role-packaged, and knowledge cannot close an evolution loop.

## Decision

1. **Two harnesses, one stack**
   - **Delivery harness** — `workflow.yaml` + prayog skills + forge ACL (unchanged ownership).
   - **Behaviour harness** — Hermes **role prompt packs** via `PromptService` only (`src/prompts/hermes.{role}.*`). Codifies *how the hire thinks* at judgment/authorize hops.
2. **Greenfield — no dual path, no dead code.** In the behaviour wave PR(s): delete inline system/user prompt construction for judgment/decide/debate, plus unused helpers and obsolete tests. Callers pass `template_id` + variables only. No “fallback inline if template missing,” no stubs left “for later.”
3. **Pack layout (SSOT)**
   - `hermes.pm.*` — keep; gold pattern (already live).
   - `hermes.pe.*` — impact challenge, grounding, Gate 1 recommend.
   - `hermes.dev.*` — debate pass, hop recommend, catalogue outcome decide, Gate 2 / board recommend overlays.
   - `hermes.kb.*` — learning harvest shape; what to write back into OKF heads.
4. **Platform extract stays code** — ADR 0003 `agentic_extract` allow-lists remain fail-closed. `agentic_decide` / Dev debate become **thin runners** over PromptService (no prompt body in Python).
5. **Knowledge loop (evolution)**
   - KB heads remain accelerator SSOT under `{tenant-meta}/knowledge/` ([adh-kb-heads.md](../references/adh-kb-heads.md)).
   - **Mode A (this wave):** inject head excerpts into prompt variables on next hop.
   - **Mode B (later, Lead-gated):** learning-extract proposes `hermes.*.yaml` diffs as PRs; Lead merges.
   - **Mode C:** auto-merge prompt packs — **out of scope / refused**.
6. **Skills stay skill-scoped.** Prayog `skills/**/prompts/` produce artefacts. They are not a substitute for Hermes role behaviour packs.

## Consequences

- Behaviour evolves by editing YAML packs (and later KB→prompt PRs), not by rewriting programme walkers.
- Every hire has a visible “how I think” surface for Lead review.
- Dead inline prompt strings are deleted in-wave — no compatibility shims.

## Non-goals

- Replacing skill templates with Hermes packs.
- Agentic Lead command classify (still ADR 0003 hole).
- Coder hire / wave PRs as OS bar **in this behaviour wave** (see [ADR 0005](0005-coder-hire.md) — separate hire).
- Auto-evolving prompts without Lead (Mode C).

## Verify slate (after greenfield land)

| INIT | Lane | Mode | Behaviour bar |
|------|------|------|----------------|
| INIT-REALWORLD-003 | Dev (B1); PE as needed (B2) | **god** | Debate/decide / PE judgment from Hermes packs only |
| INIT-REALWORLD-004 | Dev (B1); PE as needed (B2) | **human** | Same packs; Lead plays briefs |

No 001/002/007/008 on this train.
