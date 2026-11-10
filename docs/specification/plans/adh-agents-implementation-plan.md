# Implementation plan — ADH Agents Team OS

**Status:** D1–D5 + U1–U5 code landed. **Next wave U6 (mandatory) — agent↔agent clarification rally; human only after briefs settle.**  
**ADR:** [0002](../adr/0002-adh-agents-team-os.md)  
**Product:** [adh-agents-team-os.md](../product/adh-agents-team-os.md)  
**KB heads:** [adh-kb-heads.md](../references/adh-kb-heads.md)  
**As-built:** [implementation-status.md](../as-built/implementation-status.md)

This is the **work tracker SSOT**. Architecture framing: Team OS control plane + role workers — not a Hermes facade router.  
**Delivery workflow is fixed.** Product excellence means we **remove** drift (jargon Buzz, forge-click Next, mid-rally `ack_pe`, unsynced meta) — we do not leave dual paths or “optional later” for the army UX.  
**Hermes value:** army runs capped PE↔PM ping-pong + helpful briefs; human judges after settled; KB heads compound as prompt context.

---

## Work tracker (follow this)

```text
ADH Agents Team OS

0.  Product / ADR lock                              ✅
0a. PM on BaseHermesAgent + baton emit              ✅  PRs #6–#14
0b. Greenfield control plane + delete legacy        ✅  PR #16
V1. PM live on new OS (RealWorld guinea pig)        ✅
V2. PE claims pe.review → read.walk                 ✅
D1. PE: Q caps, Buzz+PR, attest                     ✅  PR #17
D2. PM glue: pe answers + prd_merge authorize       ✅  PR #17
D3. Read: one-repo walk / structured rollup         ✅
D4. KB: knowledge/ heads + enrich draft PR          ✅
D5. Harden: dup/timeout/authorize/SSE + no regex    ✅
    Gate‑1 decision paper + global temp purge       ✅  PR #21
    Forge undraft via GraphQL before merge          ✅  PR #22

── UX + land autonomy ──
U1. Helpful-army coach on BaseHermesAgent           ✅  gate_coach + delivery_voice + post_human_next
U2. Single open human gate (no cross-role resume)   ✅
U3. Shared land_pr + sync local develop             ✅
U4. KB authorize → agent land (not “merge on forge”)✅
U5. Zombie draft hygiene + unit proof               ✅  RealWorld guinea pig after U6

── next (Hermes value loop) ──
U6. Agent↔agent PE↔PM rally + post-rally human merge ✅  drop ack_pe; KB prompt context

── later hires ──
dev / qa / iac / sre / obs + codegraph MCP          ⬜
```

**Rule:** architecture is closed after 0b. Remaining work deepens programmes on this spine.  
**Product rule:** ADH is the product; RealWorld is a guinea pig only — no tenant/INIT/repo hardcoding in programmes.

---

## Hermes intent — helpful army (locked 2026-11-10)

We are a **helpful army of agents**. On Buzz the **role that did the work** posts:

1. **I did** — plain delivery language (product PR, knowledge docs PR, spec PR, …).  
2. **Recommendation** — recommend + short why.  
3. **Evidence + example** — brief/PR/ADR we generated (DecisionCard depth in the artefact).  
4. **You are the human \<role\>** — what we expect from them.  
5. **Before you post** — what to read **outside ADH** (Cursor / PR / local meta).  
6. **Exact Buzz reply** — tokens + what **I** will do after each token.

Humans **review outside ADH**; they **decide on Buzz**. Agents **execute** (including merge + refresh local develop). Never “merge it yourself on GitHub” as the primary Next.  
Internal ids (`pe.review`, Gate‑1, `kb.enrich`, catalogue node ids) stay in **logs/payloads** — not Buzz headlines.

### Delivery voice lexicon (Buzz body)

| Prefer | Avoid on Buzz |
|--------|----------------|
| product PR / product brief / product questions | Gate‑1, pe.review, meta jargon |
| knowledge docs PR / ADR updates | kb.enrich as the headline |
| spec PR / implementation PR (later) | catalogue node ids |
| merge into develop | raw forge action names as Next |
| cleaned up working notes | PurgeEvent enum names |

---

## Buzz UX contract (all roles)

Ops is for **human input and next steps**, not evidence dumps.

| Field | Rule |
|-------|------|
| **I did** | First person; delivery language |
| **Recommend** | One recommend + bluf |
| **Evidence** | Brief path and/or PR URL (`artefact_refs`) |
| **Outside ADH** | What to read before replying |
| **On Buzz** | Exact tokens + what the agent will do |
| **Never** | Full diffs, forge JSON, laundry lists, code gate names as headlines |

Progress ticks while working (still-working); one short DONE rollup. Same DecisionCard pattern in artefacts; Buzz carries the coach skeleton.

---

## Locked decisions

### Spine (unchanged)

| Topic | Choice |
|-------|--------|
| Product | ADH Team OS; RealWorld = guinea pig only |
| Package | `src/adh_agents/` only — no hermes runtime twin |
| Control plane | Orchestrator + work store + runner registry in `adh_agents/runtime` (**mandatory**) |
| Enabler | `BaseHermesAgent` = listen / baton / forge ACL / progress / **human-next coach** |
| Agents | Embed control plane; role-scoped ops filter; one process per role |
| Programmes | Register on plane; under `adh_agents/programmes/{pm,pe,read,kb}/` |
| Redis work | `adh:agent:work:{tenant}:{role}:{work_id}` |
| Workers | `make adh-pm` / `adh-pe` / `adh-read` / `adh-kb` |
| Legacy | **Deleted** in #16 |
| Sequence | OS → V1 → V2 → D1–D5 → **U1–U5** → later hires |

### D3–D5 locks (2026-11-09) — unchanged summary

D3 one-repo `repo_ref` · D4 OKF heads + post-merge `kb.enrich` · D5 reclaim/SSE/no regex SSOT · global `TempFamily`×`PurgeEvent` purge · Gate‑1 decision paper · GraphQL undraft before merge.

### Helpful-army locks (2026-11-10) — **mandatory** (fixed delivery workflow)

| # | Topic | Choice |
|---|-------|--------|
| U.1 | Who posts | **Working role only** via **`BaseHermesAgent.post_human_next`** — no ad-hoc human-gate Buzz strings |
| U.2 | Review | Outside ADH; decide on Buzz — **only** decision channel for Team OS lands |
| U.3 | Land | Authorize ⇒ undraft+merge+**sync integration branch** — **required** on every durable land |
| U.4 | Lexicon | Delivery voice on Buzz; machine ids **only** in payload/logs |
| U.5 | Routing | **Exactly one** open human gate per INIT; silent if no open brief |
| U.6 | Purge | Agent `execute_purge` after success — **required**; not a human step |
| U.7 | KB | Same authorize→land→sync as product PR — **required** |
| U.8 | Authorize bind | Token binds `{initiative, purpose, pr?, head_sha?}` — no bare cross-phase `go ahead` |
| U.9 | No dual paths | Delete forge-click Next, Gate‑1 Buzz jargon, resume spam, optional coach skips |

### Debt to **remove** this wave (do not carry)

| Debt | Removal |
|------|---------|
| “review/merge on forge” Buzz Next | Delete; coach + agent land |
| “Gate‑1” / catalogue node ids on Buzz bodies | Delivery lexicon only |
| Cross-role “Resume PE/KB…” on every Lead line | Delete unless open human gate / explicit resume |
| Idempotent baton lines on Buzz (`(idempotent) baton…`) | Log only; no ops post when `created=false` |
| Stale “PM still working on outline” labels mid-lane | Hop-accurate still-working labels |
| Swallow undraft failure then merge | Already fixed (#22); keep fail-closed land |
| Unsynced local meta after merge | **Required** `sync_integration_branch` |
| Second product draft after merge (PR #6 class) | Refuse/close superseding drafts |
| Free-text human-gate posts bypassing base | All gates call `post_human_next` |

### Agentic harness locks (2026-11-09) — still bind

H1 understand→catalogue · H2 no regex SSOT · H3 soft gates · H4 stub+LLM KB · H5 Read sensor / PE interprets · H6 ask-back on LLM-down.

---

## File-level implementation plan (U1–U5) — mandatory

### U1 — Coach on base + delivery voice (**required**)

| File | Action |
|------|--------|
| `src/adh_agents/collaboration/gate_coach.py` | **NEW** — `format_human_next` (I did / recommend / evidence / outside ADH / tokens / I will) |
| `src/adh_agents/collaboration/delivery_voice.py` | **NEW** — fixed hop→phrase map (`product_pr`, `product_brief`, `knowledge_docs_pr`, …) |
| `src/adh_agents/base.py` | **ADD** `post_human_next`; **CHANGE** baton emit: no Buzz when `created=false` |
| `src/adh_agents/collaboration/brief_service.py` | Artefact DecisionCard stays; **Buzz human gates must not** use raw `format_brief_markdown` alone |
| `src/adh_agents/programmes/pm/authoring.py` | Promote → `post_human_next` only |
| `src/adh_agents/programmes/pm/meta_pm.py` | Post-pm + open-product-PR authorize → `post_human_next` only |
| `src/adh_agents/programmes/pm/pe_glue.py` | Merge authorize → `post_human_next`; delete forge-click copy |
| `src/adh_agents/programmes/pe/gate1_brief.py` | **Rewrite** Buzz strings to product-brief voice; strip Gate‑1 from human body |
| `src/adh_agents/programmes/pe/review.py` | Questions / hold / attest prompts via agent `post_human_next`; delete jargon status lines from ops |
| `src/adh_agents/programmes/kb/enrich.py` | **Delete** “merge on forge”; coach only |
| `src/adh_agents/agents/pm_agent.py` | Programmes obtain agent/base for human-next (DI or callback) |
| `src/adh_agents/agents/pe_agent.py` | Same |
| `src/adh_agents/agents/kb_agent.py` | Same |
| `src/adh_agents/agents/read_agent.py` | Read stays BLUF+waiting-on; no fake human gate |
| `tests/unit/test_gate_coach.py` | **NEW** — forbid Gate‑1 / kb.enrich / “merge on forge” in bodies |

**Exit:** Zero human-gate Buzz posts outside `post_human_next`.

### U2 — Single open human gate (**required**)

| File | Action |
|------|--------|
| `src/adh_agents/runtime/orchestrator.py` | Lead text binds **only** open judgment/authorization brief; fence `prd_merged` from draft-PR reopen |
| `src/adh_agents/agents/pe_agent.py` | **Remove** resume-on-any-Lead; resume only explicit / open gate |
| `src/adh_agents/agents/kb_agent.py` | Same |
| `src/adh_agents/agents/pm_agent.py` | `go ahead` matches open brief purpose only |
| `src/adh_agents/runtime/work_models.py` | If needed: purpose/slot for authorize bind (`pr_number`, `head_sha`) |
| `tests/unit/test_adh_orchestrator.py` | **Required** cases: post-merge go-ahead → KB only; PE silent |

**Exit:** One Lead message → one gate; debt resume spam gone.

### U3 — Land + sync (**required** on every durable land)

| File | Action |
|------|--------|
| `src/infra_services/forge_action_service.py` | **ADD** `land_pull_request` (undraft+merge); `prd_merge` → calls it |
| `src/infra_services/github_app_service.py` | GraphQL undraft (landed) |
| `src/infra_services/pm_workspace_service.py` | **ADD** `sync_integration_branch` — dirty → stall coach (`discard local` / `hold`) |
| `src/adh_agents/programmes/pm/pe_glue.py` | authorize → land → sync → purge → DONE coach |
| `tests/unit/test_workspace_sync.py` | **NEW** |
| `tests/unit/test_github_ready_for_review.py` | Keep |

**Exit:** After product merge, local meta **equals** `origin/develop` or explicit stall — never silent drift.

### U4 — Knowledge docs PR land (**required**)

| File | Action |
|------|--------|
| `src/adh_agents/programmes/kb/enrich.py` | Brief + coach; `go ahead` → `land_pull_request` + sync + purge **after** land |
| `src/adh_agents/collaboration/temp_papers.py` | `KB_ENRICH_DONE` only post-land |
| `src/adh_agents/forge_acl/__init__.py` | **KB** allowed to land/merge knowledge PRs |
| `src/adh_agents/agents/kb_agent.py` | Orchestrator + judgment → land path |
| `tests/unit/test_kb_enrich_land.py` | **NEW** |

**Exit:** Knowledge docs PR never asks human to merge on GitHub.

### U5 — Hygiene + proof (**required**)

| File | Action |
|------|--------|
| `src/adh_agents/programmes/pm/meta_pm.py` | After product merge: **refuse** new product draft for same INIT unless explicit new intent |
| Forge close helper (workspace or forge_action) | Close superseding open product drafts for that INIT |
| `docs/specification/*` | Already seeded; tick as-built when green |
| RealWorld proof | Coach → land+sync → KB land → no second product review |

**Exit:** No PR #6-class debt; guinea pig green.

### Order (fixed)

```text
U1 → U2 → U3 → U4 → U5
```

No parallel “optional coach later.” U1/U2 before U4 so KB land cannot regress routing.

---

## U6 — Agent↔agent clarification rally (mandatory)

### Product lock (2026-11-10)

```text
PE asks (PR + brief) → PM answers (PR + answers brief) → ≤2 agent rounds
  → PE attests when settled (agent)
  → PM posts “clarifications settled” coach
  → Human reviews briefs outside ADH → merge / park
  → land + sync → KB enrich (heads become next-run prompt context)
```

| # | Lock |
|---|------|
| U6.1 | **No** human mid-rally (`ack_pe` deleted) |
| U6.2 | Default **`max_question_rounds = 2`** |
| U6.3 | PM **auto-answers** on product PR (LLM + Impact-Map + OKF heads) |
| U6.4 | PE may one follow-up round from answers; then stop |
| U6.5 | After settle: PE **agent attest**; PM opens **only** human merge coach |
| U6.6 | Human reply lexicon: `merge the product PR` / `park` (aliases: `go ahead`) |
| U6.7 | KB heads **read** into PE question gen + PM answer prompts (thin now; compound later) |
| U6.8 | Dead paths removed — no dual “human ack OR auto answer” |

### Debt to delete

| Debt | Removal |
|------|---------|
| `ack_pe` / stage `pm-pe-acked` / human `pm-pe-answers` gate | Delete |
| Human-required `attest` before merge-ready | PE attests after settle (Lead may still `park`) |
| `max_question_rounds` default 4 | Default 2 |
| Forge jargon reply tokens at merge | Human phrases + aliases |
| PE/PM prompts ignoring `knowledge/` | Shared OKF context loader |
| Idempotent baton Buzz spam in PE emit helpers | Log only (match base.emit_baton) |

### Target baton flow

```text
pe.review
  → read.walk (unchanged)
  → PE questions round 1 + brief + PR comment
  → baton pm.pe_questions
PM answers on PR + answers artefact (no human gate)
  → baton pe.pm_answers
PE evaluates: follow-up round 2 OR settle
  → if round 2: questions again → pm.pe_questions (final)
  → if settle: PE attest → baton pm.prd_merge_ready
PM opens human merge coach only
  → human: merge the product PR | park
  → land + sync + kb.enrich
```

### File-level plan

#### U6a — Shared OKF prompt context + human lexicon (**required**)

| File | Action |
|------|--------|
| `src/adh_agents/collaboration/okf_context.py` | **NEW** — load thin OKF excerpts from `knowledge/{foundation,stacks,repos,contracts}` for initiative/repos; empty-safe |
| `src/adh_agents/collaboration/human_replies.py` | **NEW** — canonical reply phrases + aliases (`merge the product PR` ↔ `go ahead` / `authorize prd_merge`; `park` ↔ `hold`) |
| `src/adh_agents/collaboration/gate_coach.py` | Prefer human phrases in TokenAction examples |
| `src/adh_agents/collaboration/delivery_voice.py` | Add hops: `clarifications_settled`, `product_answers` |
| `tests/unit/test_okf_context.py` | **NEW** — missing heads → empty; present heads truncated |
| `tests/unit/test_human_replies.py` | **NEW** — alias normalization |

**Exit:** One loader; one lexicon SSOT. No programme-private synonym tables.

#### U6b — PM auto-answer programme (**required** — replace ack gate)

| File | Action |
|------|--------|
| `src/adh_agents/programmes/pm/pe_answers.py` | **NEW** — greenfield: load questions artefact; PromptService/LiteLLM answer; write `prd/reports/{INIT}-pm-pe-answers.md`; `comment_pr` on product PR; optional minimal PRD note section; emit `pe.pm_answers` |
| `src/adh_agents/programmes/pm/pe_glue.py` | **REWRITE** — `pm.pe_questions` → call `pe_answers` (no human gate). Keep merge authorize path only; use human_replies lexicon |
| `src/adh_agents/forge_acl/__init__.py` | PM may `comment_pr` (answers on product PR) |
| `src/adh_agents/agents/pm_agent.py` | Catch `pm.pe_questions` → pe_glue/pe_answers; drop any ack_pe handling |
| `src/adh_agents/runtime/work_models.py` | Drop reliance on `pm-pe-answers` / `pm-pe-acked` stages (or mark obsolete) |
| `tests/unit/test_pm_pe_answers.py` | **NEW** — answers artefact shape; emits `pe.pm_answers`; **no** open brief |

**Exit:** Zero `ack_pe` in repo. `pm.pe_questions` never opens AWAITING_JUDGMENT.

#### U6c — PE settle loop + agent attest (**required**)

| File | Action |
|------|--------|
| `src/adh_agents/programmes/pe/settle.py` | **NEW** — consume `pe.pm_answers`; decide follow-up vs settle (round < 2 and open deltas → round 2; else settle) |
| `src/adh_agents/programmes/pe/review.py` | Wire settle; after settle call `_attest` then `pm.prd_merge_ready`; progress Buzz only mid-rally (no human gate); delete human-required attest as the happy path |
| `src/adh_agents/programmes/pe/gate1_brief.py` | Post-settle brief variant: “clarifications settled — human review for merge”; delivery voice |
| `src/adh_agents/programmes/pe/questions.py` | Optional: pass OKF context into recommendations; strip Gate‑1 jargon from human-facing question docs |
| `src/adh_agents/agents/pe_agent.py` | Handle `pe.pm_answers` baton; keep Lead `park` / explicit `need another round` escape only; remove mid-rally ack dependency |
| `src/adh_agents/settings.py` | `max_question_rounds` default **2**; document agent rally |
| `src/adh_agents/baton/models.py` / emit sites | Register types `pe.pm_answers` (and keep `pm.pe_questions`, `pm.prd_merge_ready`) |
| `tests/unit/test_pe_settle.py` | **NEW** — round1→answers→settle; round1→answers→round2→settle; cap stop |

**Exit:** Happy path reaches merge coach with **no** human Buzz between draft-open and merge authorize (except optional `park`).

#### U6d — Post-rally human merge coach only (**required**)

| File | Action |
|------|--------|
| `src/adh_agents/programmes/pm/pe_glue.py` | `_open_merge_gate` / DONE coach: “Clarifications settled. Review briefs outside ADH.” Tokens via `human_replies` |
| `src/adh_agents/programmes/pm/meta_pm.py` | Ensure resume never reopens pe-answers human gate |
| `src/adh_agents/runtime/orchestrator.py` | Bind aliases through human_replies when matching tokens |
| `tests/unit/test_merge_lexicon.py` | **NEW** — `merge the product PR` and `go ahead` both land path |

**Exit:** One human judgment after settle = land or park.

#### U6e — Docs + dead code sweep + proof (**required**)

| File | Action |
|------|--------|
| Grep purge | Delete all `ack_pe`, `pm-pe-acked`, “ack the answers” human copy |
| `docs/specification/product/adh-agents-team-os.md` | Lock U6 rally + human-after-briefs |
| `docs/specification/plans/adh-agents-implementation-plan.md` | This section |
| `docs/specification/as-built/implementation-status.md` | Tick U6 when green |
| RealWorld scratch guinea pig | After U6: outline→…→army Q&A (no ack_pe)→merge coach→KB |

**Exit:** Guinea pig transcript matches product lock; no mid-rally human tokens.

### Order (fixed)

```text
U6a (context + lexicon) → U6b (PM answers) → U6c (PE settle + attest) → U6d (merge coach) → U6e (sweep + proof)
```

---

## Develop merge ledger (recent)

| PR | Summary |
|----|---------|
| #17 | PE questions/attest + PM pe_glue / `prd_merge` |
| #21 | Gate‑1 decision paper + global temp purge |
| #22 | GraphQL undraft before `prd_merge` |
| next | U1–U5 helpful-army coach + land/sync |

---

## Layout (landed + planned)

```text
src/adh_agents/
  base.py                 # + post_human_next
  collaboration/
    brief_service.py
    temp_papers.py
    gate_coach.py         # NEW
    delivery_voice.py     # NEW
  runtime/orchestrator.py # U2 routing
  programmes/pm|pe|read|kb/
  agents/

src/infra_services/
  forge_action_service.py # + land_pull_request
  github_app_service.py   # GraphQL undraft
  pm_workspace_service.py # + sync_integration_branch
```

---

## Success bar

| Gate | Bar |
|------|-----|
| D1–D5 | As before (PE/PM/read/kb/harden/purge/undraft) |
| U1 | Working role posts coach; delivery lexicon; outside-ADH + exact tokens |
| U2 | One open human gate; no false PE/KB resume on Lead tokens |
| U3 | Authorize → merge + local develop == `origin/develop` |
| U4 | KB `go ahead` lands knowledge PR; no “merge on forge” Next |
| U5 | No zombie product draft after merge; RealWorld proof |

## Out of scope (unchanged)

- Stratum 20-repo production fan-out  
- Full QA docker programme  
- Codegraph MCP (port stub until later hire)  
- Reviving HermesService / dual session stores  
- TaskGraph as a separate hire (Impact-Map remains SSOT for repo DAG until then)  
- Replacing Cursor/IDE as the human reading surface  
