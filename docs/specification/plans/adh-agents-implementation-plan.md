# Implementation plan — ADH Agents Team OS

**Status:** D1–D5 + U1–U6 + **Floor F1–F9** landed on `develop` ([PR #25](https://github.com/drivestream-lab/adh/pull/25)). God guinea pig `INIT-REALWORLD-004` archived.  
**ADR:** [0002](../adr/0002-adh-agents-team-os.md)  
**Product:** [adh-agents-team-os.md](../product/adh-agents-team-os.md)  
**KB heads:** [adh-kb-heads.md](../references/adh-kb-heads.md)  
**As-built:** [implementation-status.md](../as-built/implementation-status.md)

This is the **work tracker SSOT**.  
**No legacy / dual paths.** Greenfield replacements delete the old path in the same PR.  
**ADH is the product**; RealWorld is guinea pig only.

---

## Work tracker

```text
ADH Agents Team OS

0–0b / V1–V2 / D1–D5     ✅  PRs #6–#22 (spine, Gate‑1, read/kb, purge, undraft)
U1–U5 helpful-army land  ✅  coach, single gate, land+sync, KB land, hygiene
U6 PE↔PM agent rally     ✅  PR #23; ack_pe gone; human merge after settle
KB land approve-before   ✅  PR #24; reopen Buzz gate on stall
F1–F9 Team floor         ✅  PR #25; god INIT-004 → archive; traj hub mirrors

── done (PM lane A+B) ──
H1 Human rewind + traj    ✅  PR #27; 006 promote rewind+traj; 005 post-merge `rewind_denied`
Human INIT-005 verify     ✅  full human forward → archive; hub traj mirrors

── landed (E1 Dev YAML) ──
E1 Dev engg = workflow.yaml  ✅  develop tip; Gate2 + engg isolation (#30/#31); 002 board-seeded

── planning (greenfield — no dual path) ──
B0–B3 Hermes behaviour harness  🟨  single PR — ADR 0004 Accepted; packs+runners landed in branch;
                                 live verify **003 god / 004 human** after merge
                                 [hermes-behaviour-harness-plan.md](hermes-behaviour-harness-plan.md)

── later ──
Coder hire (`adh.coder`) + verify agent + qa / iac / sre / obs + codegraph MCP + TaskGraph   ⬜
```


---

## Locked decisions (Floor wave)

| # | Lock |
|---|------|
| F.1 | **Postgres** = durable chat (rooms, members, messages, tasks, archive, `buzz_task_events`) |
| F.2 | **Redis** = live OS only (sessions **7d**, batons **1d**, presence, short god-chain) — **never** chat/archive/trajectory SSOT |
| F.3 | **No Redis Task SSOT** — canonical task = `buzz_tasks` |
| F.4 | Hub `#{tenant}-ops` + task `#task-{TASK_ID}`; Lead `archive task` / `delete task` / `keep open` |
| F.4b | Hub = intake/announce only; **all** bound-INIT army/coach talk in task room; baton `ops_room` = task slug |
| F.5 | Ingress: `init` ← outline; `bug`/`enhancement` ← GH **bind API + poll stub** (RealWorld label path) |
| F.6 | UI: last **20**, scroll-up page, stick-to-latest; sidebar active task rooms; **desktop only** — delete duplicate `buzz_ui` |
| F.7 | Workers listen **hub + all non-archived task rooms** |
| F.8 | CollabPost on baton emit/claim/done; batons remain claim SSOT |
| F.9 | God: `ADH_AUTONOMY_MODE=god`; GateOpener plays `recommend ∈ reply_tokens`; Lead ignored on open gates; halt → `god_mode_halt` |
| F.10 | Trajectory = **`buzz_task_events` only** — no trajectory files in meta git |
| F.11 | Done coach recommends **`archive task`**; god never auto-**delete**; `discard local` still allow-flag only |
| F.12 | Guinea pig: **1 INIT human**, then **1 INIT god** → KB land |
| F.13 | Ship **F1–F9 in a single PR** (wave-ordered commits OK) |
| F.14 | **Delivery harness** — `buzz_tasks` kind (`init`/`bug`/`enhancement`) + state (`bound`→`running`→`gated`→`done`/`halted`→`archived`) is resume SSOT; catch-up never replays full chat history |
| F.15 | **Hub → task UX** — hub one-liner always; desktop **guarded auto-switch** to `#task-…` when Lead is on that tenant hub (never steal focus from another active task room) |
| F.16 | **Trajectory hub mirror** — every `buzz_task_events` append also posts a **Buzz-light** one-liner on `#{tenant}-ops` (pointer + kind/state; no evidence dumps). SSOT remains PG events |
| F.17 | **God: no rewind.** Rewind/reason gates are human-mode only (later). God plays forward `recommend` or `god_mode_halt` |
| F.18 | **Ingress:** outline → `init` only; `bug`/`enhancement` → GitHub ticket bind only (no Buzz outline creates bug/enh) |

---

## Floor polish → god verify (file-level plan)

**Goal:** Finish collab/harness polish that blocks a clean god-mode guinea pig, then run verify INIT #2 (`ADH_AUTONOMY_MODE=god`).

**Order:** T1 → T2 → T3 → T4 → T5 → **god verify**. Do not start god verify until T1–T4 green.

### T1 — Trajectory densify + hub mirror

| File | Change |
|------|--------|
| `src/models/buzz_models.py` | Ensure `TaskEventKind` covers: `GATE_OPEN`, `GOD_TAKEN`, `GOD_HALT`, `BATON`, `LAND`, `ARCHIVE`, `DELETE`, `INGRESS`, **`STATE`** (optional), **`REWIND`/`REWIND_DENIED`** stubs OK unused in god |
| `src/business_services/buzz_service.py` | In `append_task_event`: after PG insert, **hub mirror** — `post_message` on task’s `hub_room_slug` (Buzz-light: ``traj `{kind}` `{task_id}` → #{task_room}`` + state). Fail-open (log, never fail the event write). Idempotent-ish: payload `traj_mirror: true` |
| `src/adh_agents/runtime/gate_opener.py` | Already writes gate/god events + `set_task_state(GATED/HALTED)`; confirm hub mirror via service |
| `src/adh_agents/base.py` | Baton trajectory rows already; ensure claim/done paths hit `append_task_event` |
| `src/adh_agents/programmes/pm/pe_glue.py` | On product merge land+sync success → `TaskEventKind.LAND` + `set_task_state(RUNNING)` or keep gated until KB; on full product done before KB prefer stay `running` |
| `src/adh_agents/programmes/kb/enrich.py` | On knowledge land+sync success → `LAND` + `set_task_state(DONE)` then archive coach |
| `src/adh_agents/programmes/pm/task_lifecycle.py` | Archive/delete already; DONE before archive coach (done) |
| `src/adh_agents/programmes/pm/authoring.py` | RUNNING after bind (done); refuse non-`init` if any outline path tries other kinds |
| `tests/unit/test_traj_hub_mirror.py` | **NEW** — append_task_event posts hub mirror once; event row exists |

### T2 — Desktop guarded auto-switch + listening strip

| File | Change |
|------|--------|
| `apps/buzz-desktop/src/main.ts` | On hub SSE `payload.status=task_opened`: if `currentSlug === hub` for that tenant → `openRoom(task_room_slug)`; if already in another `task-*` → refresh sidebar + unread badge only (no focus steal). Parse `task_room` / `task_id` from payload |
| `apps/buzz-desktop/src/main.ts` | Room header: **Listening** strip — members (PG) + presence dot if Redis/API available; poll members on `openRoom` + every ~15s |
| `src/api/v1/buzz_router.py` | If missing: `GET …/rooms/{slug}/members`; optional `GET …/presence?room=` or fold presence into members DTO later |
| `src/business_services/buzz_service.py` | `list_members` already — expose cleanly; presence list helper if needed |
| `src/adh_agents/runtime/presence.py` | Ensure heartbeat keys queryable by room (or by tenant+role); document key shape |
| `apps/buzz-desktop` CSS | Compact roster chips (`adh.pm ●`) |

### T3 — Catch-up / harness hygiene (mostly landed — close gaps)

| File | Change |
|------|--------|
| `src/adh_agents/agents/pm_agent.py` | Task-room catch-up: open PM gate + latest unacked Lead only (**done**) |
| `src/adh_agents/runtime/catch_up.py` | Policy helpers (**done**) |
| `src/adh_agents/runtime/orchestrator.py` | `_say` uses bound `role_id` (**done**); ingest ack (**done**) |
| `src/adh_agents/runtime/room_resolve.py` | `collaboration_room` for army posts (**done**) |
| `src/adh_agents/ingress/github_ingress.py` | Only path for `bug`/`enhancement`; outline path never creates those kinds — assert in authoring |
| `src/adh_agents/programmes/pm/authoring.py` | Hard-lock `TaskKind.INIT` on outline bind |

### T4 — Product/plan copy locks

| File | Change |
|------|--------|
| `docs/specification/product/adh-agents-team-os.md` | F.15–F.18: hub mirror traj; guarded auto-switch; god no rewind; GH-only bug/enh; listening = members + presence |
| `docs/specification/plans/adh-agents-implementation-plan.md` | This section (SSOT) |
| `docs/specification/as-built/implementation-status.md` | Mark T1–T4 / god verify bar |

### T5 — God verify (after T1–T4)

| Step | Bar |
|------|-----|
| Set `ADH_AUTONOMY_MODE=god` in `.env`; restart PM/PE/Read/KB | Workers ready |
| Clean or new RealWorld INIT outline on hub | Task opens; desktop switches if on hub; hub traj lines appear |
| Zero Lead gate tokens through product path | `buzz_task_events` shows `god_taken` (not human); hub mirrors each |
| Hermes judges; god only auto-plays **recommend ∈ reply_tokens** | Promote / post-pm confirm / merge / land — GateOpener; halt if unplayable |
| Promote → meta-pm chain in god | No Lead `post-pm` kickoff; authoring `_god_chain_post_pm` + boot resume seam |
| Forge recommend = Lead token | `brief_authorization.recommend=go ahead` (was `authorize` ∉ tokens) |
| Dirty-meta sync in god | `ADH_GOD_ALLOW_DISCARD=true` required for Hermes `discard local` |
| KB land without Lead | `LAND` + `DONE` |
| Archive in god | GateOpener recommend `archive task` auto-plays; **`delete task` never** (halt token) |
| Confirm no rewind prompts in god | Halt only if recommend unplayable |

**Guinea pig:** `INIT-REALWORLD-004` (god) → product PR #12 + knowledge PR #13 → `LAND` → **`archive task` god_taken** → `state=archived` (by `adh.system`).

**Human INIT #1** can finish in parallel (`go ahead` on KB land) but **god verify is the exit** for this polish wave.

### Explicitly deferred (not in T1–T5)

- Dev/QA hire + catalogue-on-demand membership (north star; not blocking god)
- Per-wave child rooms (rejected: one `#task-…` war room)
- Trajectory UI timeline panel — use Buzz `traj` card + hub mirrors instead
- Git un-merge / revert after develop land — **outside ADH**

---

## H1 — Human rewind + traj-on-Buzz

**Locks:** God = no rewind. Post–product-merge = deny (git undo outside ADH). Coach always shows **Can / Cannot / Outside ADH**. Always reason + `confirm rewind`. Close open draft PRs we raised when crossing that fence. Purge per matrix (`start` = all thinks; promote re-pick = keep thinks). Same task room on `start` (outline again). Traj query on Buzz: kind | purpose | token | who.

| File | Change |
|------|--------|
| `src/adh_agents/runtime/rewind.py` | Ladder `can` / `cannot` / `outside` + purge/close flags |
| `src/adh_agents/collaboration/temp_papers.py` | `PurgeEvent.REWIND_*` + promoted PRD family |
| `src/adh_agents/programmes/pm/rewind_coach.py` | Menu → confirm → execute |
| `src/adh_agents/programmes/pm/traj_coach.py` | Lead `traj` Buzz card |
| `src/adh_agents/agents/pm_agent.py` | Route rewind / traj |
| `src/adh_agents/forge_acl` | `close_pull_request` for PM/KB |

**Shipped:** [PR #27](https://github.com/drivestream-lab/adh/pull/27).

---

## E1 — Dev engg lane = `workflow.yaml` (greenfield rewrite)

**Intent:** Hire **`adh.dev`** as the **development / engg** catalogue consumer — same pattern as the PM lane.  
**SSOT:** [`prayog-skills/workflow.yaml`](../../../prayog-skills/workflow.yaml) `sdd-delivery/v2` **`development`** entry (`spec-draft` → … → `board-tickets-action`).  
**No legacy / no dual spine.** Delete the invented programme stages (including **`deps-acceptance`**) and rewrite Dev to walk YAML only.

**Product fence → engg:** After **`prd-merge`**, PE → Dev baton opens `#engg-<id>`. Dev runs skills + forge against the **Impact-Map repos** (PRD + codebase → **spec**), not a meta-only report theatre.  
**Coder** (`adh.coder` / `loop-spec` waves) stays **out of E1**.

**Live slate reset (2026-11-11):** Deleted `#engg-init-realworld-001`, `#task-init-realworld-001`, task row/events, and Redis work/baton/god-chain for **INIT-REALWORLD-001**. Guinea pigs restart from scratch after the rewrite.

**Verify slate (RealWorld guinea pig — after rewrite):**

| INIT | Lane | Product PRD PR | Mode |
|------|------|----------------|------|
| INIT-REALWORLD-001 | **Dev** engg | [#5](https://github.com/drivestream-lab/realworld-meta/pull/5) | **god** — full YAML development chain |
| INIT-REALWORLD-002 | **Dev** engg | [#8](https://github.com/drivestream-lab/realworld-meta/pull/8) | **human** — Lead plays YAML checkpoints from briefs |
| INIT-REALWORLD-007 | **PM + PE** | (product lane) | **god** |
| INIT-REALWORLD-008 | **PM + PE** | (product lane) | **human** — Lead manual from briefs |

**Platform (same PR):** `runtime/agentic_extract.py` + `agentic_decide.py` + `lead_commands.py` (phrase lists + agentic hole). No regex under `src/adh_agents/`. See [ADR 0003](../adr/0003-platform-agentic-extract-decide.md).

### Locks (greenfield)

| # | Lock |
|---|------|
| L1 | Buzz role `adh.dev`; collaboration floor `#engg-<id>` |
| L2 | **`workflow.yaml` is the only stage SSOT** for engg (like PM). No invented hops |
| L3 | PE → Dev baton after product fence (`prd-merge` / merged PRD URL OK). PM does **not** start Dev |
| L4 | Development `pass` chain (verbatim from YAML): `spec-draft` → `spec-pr-action` → `initiative-feasibility` → `spec-technical-review` → `technical-review-approval` → `spec-implementation-plan` → `coding-readiness` → `spec-merge` → `board-tickets-action` |
| L5 | Skills use `forge.commit_workspace` / forge actions as YAML declares — work the **impacted code repos + spec PR**, not meta-only stubs |
| L6 | GateOpener only on YAML **human-checkpoint** nodes (`technical-review-approval`, `coding-readiness`, `spec-human-decision`, …) |
| L7 | **God** plays `recommend` and **must progress** — same-purpose re-entry (`another round` / iterate) allowed until debate/chain cap; halt only on unplayable recommend or hard cap (**fix duplicate-purpose halt**) |
| L8 | Human mode: Lead decides from brief on `#engg-<id>`; examples / locking / BLUF |
| L9 | Board seed only when YAML predicates hold (`spec-pr-merged`, plan current, WorkManifest contract) |
| L10 | Traj: hub Buzz-light mirrors; Lead detailed `traj` card on **ops** only |
| L11 | Lead `hire engg` = escape hatch only |
| L12 | **Delete dead code** in the same PR: old `DevEnggProgramme` spine, `deps-acceptance` / Engg-Deps programme gate, verification-plan programme SSOT, any dual path |
| L13 | Multi-pass debate (cap default 4) may support YAML judgment hops — not a substitute for catalogue nodes |
| L14 | Guinea pig **after** rewrite only; wipe prior engg/task rooms for that INIT before re-run |

### Delete (no stubs)

| Remove | Reason |
|--------|--------|
| Programme stages not in YAML (`deps-acceptance`, early board-as-done, …) | Invented spine |
| `programmes/dev/deps.py` Engg-Deps **gate** path | Not a workflow node |
| `verification_plan.py` as programme SSOT | Plan skill / WM owns that |
| Meta-only “report theatre” that skips `spec-draft` / `spec-pr-action` / `spec-merge` | Violates YAML |
| God chain “duplicate purpose” hard-stop for loop tokens | Blocks autopilot |

**Keep / thin-wrap:** `DevAgent` host, PE `engg_handoff`, `RoomKind.engg`, Buzz UI Engg section, traj-on-ops, debate helper (rewired to YAML purposes).

### File-level plan (new greenfield PR)

Branch from `develop` (PR #28 scaffold is **not** sacred — replace Dev programme).

```text
G0 docs → G1 delete dead Dev spine → G2 YAML programme walker
  → G3 forge: spec-pr / spec-merge / board predicates
  → G4 god same-purpose re-entry → G5 units → G6 live verify 001/002 + 007/008
```

| Step | Scope |
|------|--------|
| **G0** | This plan + Team OS Dev section = YAML quote; as-built row; ADR 0003 |
| **G1** | Delete/replace `programmes/dev/programme.py` + deps/verification_plan programme paths; tests that asserted old spine |
| **G2** | New Dev programme: load `development` entry from workflow projection; advance only on YAML outcomes |
| **G3** | Dispatch `spec-draft` … forge `spec-pr-action`, `spec-merge`, `board-tickets-action` per pin |
| **G4** | `AutonomyPolicy.record_take` — allow re-open of same purpose for loop tokens / within cap |
| **G5** | Units: YAML order, no `deps-acceptance`, god re-entry, board predicates; `rg` clean (no `re` under `adh_agents`) |
| **G6** | Fresh rooms: Dev **001 god / 002 human**; PM+PE **007 god / 008 human**; army restart; evidence in PR |

### Out of scope (E1)

`adh.coder`, `pre-implement` / `loop-spec` / wave PRs as OS bar, codegraph MCP productization, collapsing engg into task room, inventing catalogue nodes in ADH.

---


## Storage map (code-level)

| Store | Today | Floor wave |
|-------|--------|------------|
| PG `buzz_identities/rooms/messages` | Hub ops + messages | + task rooms, members, tasks, events, archive |
| Redis `adh:agent:work:*` | Sessions 48h | **7d** TTL refresh |
| Redis `adh:baton:*` | Handoffs 1d | unchanged role |
| Redis presence | thin heartbeats | explicit presence keys |
| Disk meta | prd/ + knowledge/ | unchanged artefact SSOT |

---

## F1–F9 — file-level plan (single PR)

### F1 — Message API: latest window + cursor pagination

| File | Action |
|------|--------|
| `src/models/buzz_models.py` | Add `MessagePage` (`items`, `has_more`) |
| `src/business_services/buzz_service.py` | `list_messages(slug, *, limit=20, before_id=None)`; chrono ascending; `has_more` |
| `src/api/v1/buzz_router.py` | `limit` default **20**; `before_id`; return page |
| `tests/unit/test_buzz_list_messages.py` | **NEW** |

**Exit:** `GET …/messages?limit=20` and `?before_id=` against Postgres only.

### F2 — Buzz desktop UI

| File | Action |
|------|--------|
| `apps/buzz-desktop/src/main.ts` | Load 20; scroll bottom; near-top prepend via `before_id`; SSE stick; jump-to-latest; sidebar active task rooms (after F3) |
| `apps/buzz-desktop/src/style.css` | Load-earlier + jump-to-latest |
| `src/api/buzz_ui/index.html` | **DELETE** (no dual UI) — desktop only |

**Exit:** Cursor-like thread; no full-room dump.

### F3 — Postgres tasks, members, archive, trajectory

| File | Action |
|------|--------|
| `src/database/postgres/schema/buzz_schema.py` | **ADD** `BuzzTaskSchema`, `BuzzRoomMemberSchema`, `BuzzTaskEventSchema`; room kinds `ops\|task` |
| `postgres_migrations/versions/<ts>_buzz_tasks_members_events.py` | **NEW** |
| `src/models/buzz_models.py` | Task / Member / Event / Archive DTOs |
| `src/business_services/buzz_service.py` | create task+room, list active/archived, archive, delete (purge messages+room), ensure_member, list_members, append_task_event |
| `src/api/v1/buzz_router.py` | Task + member + archive/delete + events read routes |
| `tests/unit/test_buzz_tasks.py` | **NEW** — unique `source_ref`; archive hides; delete purges |

**Exit:** Durable task model; trajectory table ready (writers in F5/F8).

### F4 — Redis live-only (TTL + presence)

| File | Action |
|------|--------|
| `src/adh_agents/settings.py` | `work_ttl_seconds` default **604800** (7d); presence TTL; document baton 1d |
| `src/adh_agents/runtime/work_store.py` | Confirm TTL refresh on every save |
| `src/adh_agents/runtime/presence.py` | **NEW** — short-TTL presence keys |
| `src/adh_agents/base.py` | Refresh presence while listening |
| `tests/unit/test_presence.py` | **NEW** |
| **Forbidden** | Any `adh:messages:*` or Redis archive |

**Exit:** Gates survive 7d; chat untouched by Redis flush.

### F5 — Hub join + CollabPost

| File | Action |
|------|--------|
| `src/adh_agents/base.py` | Boot: ensure identity + hub member; presence |
| `src/adh_agents/surface/buzz_poster.py` | `post_collab(...)` |
| `src/adh_agents/base.py` emit_baton | CollabPost on create (task room); no idempotent spam |
| Claim/done sites | `programmes/pe/review.py`, `pm/pe_glue.py`, `kb/enrich.py`, `read/walk.py`, `execution/dispatch_service.py` |
| `tests/unit/test_collab_post_baton.py` | **NEW** |

**Exit:** Army @-talk visible; baton NX unchanged.

### F6 — Outline → task room; multi-room listen

| File | Action |
|------|--------|
| `src/adh_agents/programmes/pm/authoring.py` | On outline bind: PG task `kind=init` + task room; hub announce; `session.room` = task room |
| `src/adh_agents/baton/models.py` | `ops_room` = task room for army hops |
| `src/adh_agents/base.py` / agents | Subscribe hub + `list_active_task_rooms(tenant)` |
| `src/business_services/buzz_service.py` | `list_active_task_rooms` |
| `src/adh_agents/runtime/orchestrator.py` | Gates bind in task room context |
| `tests/unit/test_outline_opens_task_room.py` | **NEW** |

**Exit:** INIT talk lives in `#task-INIT-…`.

### F7 — Archive / delete tokens + UI lists

| File | Action |
|------|--------|
| `src/adh_agents/collaboration/human_replies.py` | `archive task` / `delete task` / `keep open` |
| `src/adh_agents/programmes/pm/task_lifecycle.py` | **NEW** (or wire meta_pm/pe_glue) — after done/halt coach archive |
| `apps/buzz-desktop/src/main.ts` | Active vs archived lists; archived read-only |
| `tests/unit/test_task_archive_tokens.py` | **NEW** |

**Exit:** Lead puts work away without destroying history (unless delete).

### F8 — GateOpener + god mode + trajectory writers

| File | Action |
|------|--------|
| `src/adh_agents/runtime/autonomy.py` | **NEW** — `human\|god`; halt tokens refused; chain cap (Redis short); recommend ∈ reply_tokens |
| `src/adh_agents/runtime/gate_opener.py` | **NEW** — save brief, coach, human return \| god `on_token` + Buzz audit + **`buzz_task_events`** |
| `src/adh_agents/settings.py` | `AdhAutonomySettings` (`ADH_AUTONOMY_MODE`) |
| `src/di/…` | Bind AutonomyPolicy + GateOpener singletons |
| Route all live gates | `authoring.py`, `meta_pm.py`, `pe_glue.py`, `kb/enrich.py` — **only** GateOpener; delete direct open_brief clusters |
| Fence | Unit/CI: no new `awaiting = AWAITING_JUDGMENT` outside `gate_opener.py` |
| `tests/unit/test_autonomy_policy.py` | **NEW** |
| `tests/unit/test_gate_opener.py` | **NEW** |

**Exit:** God env closes gates via Hermes recommend; trajectory rows in PG; Lead ignored while god.

### F9 — GitHub ingress stub (guinea pig)

| File | Action |
|------|--------|
| `src/adh_agents/ingress/github_ingress.py` | **NEW** — bind API: issue/label → PG task `bug\|enhancement` + room; unique `source_ref` |
| Poll stub | Minimal RealWorld label path (one poll/loop or make target) — **no** dual webhook path in this PR |
| Fail closed | Missing hired role → Buzz stall |
| `tests/unit/test_github_ingress_bind.py` | **NEW** |

**Exit:** One labeled GH issue binds a task room; full Dev graph still later hire.

---

## Commit order inside the single PR

```text
F1 → F2 → F3 → F4 → F5 → F6 → F7 → F8 → F9
```

---

## Guinea pig (RealWorld)

| # | Mode | Bar |
|---|------|-----|
| 1 | `ADH_AUTONOMY_MODE=human` | Outline → task room → pagination/CollabPost → PE↔PM → merge → KB → **archive task** |
| 2 | `ADH_AUTONOMY_MODE=god` | New outline → zero Lead gate tokens → KB land; `buzz_task_events` + **hub traj mirrors** show `god_taken` per gate; halt not auto-played; **no rewind** |

---

## Debt to delete in this PR

| Debt | Removal |
|------|---------|
| Default message dump limit 200 in UI | UI uses 20 + cursor |
| `src/api/buzz_ui/index.html` dual client | Delete |
| Direct gate open_brief+post clusters | GateOpener only |
| Machine-only baton Buzz as primary collab UX | CollabPost |
| Any Redis message/archive design | Forbidden |
| Trajectory markdown under `prd/reports/` | Forbidden |
| “One ops room forever / no per-task rooms” product copy | Superseded by hub+task |

---

## Success bar

| Gate | Bar |
|------|-----|
| F1–F2 | Last 20 + scroll-up page; live stick-to-bottom |
| F3 | Tasks/members/events/archive in Postgres |
| F4 | Work TTL 7d; presence; no chat in Redis |
| F5–F6 | Hub roster; task room army talk; multi-room listen |
| F7 | Archive/delete Lead-controlled |
| F8 | God INIT with trajectory; human INIT still works |
| F9 | GH bind stub creates task without double-bind |

---

## Out of scope (this PR)

- Webhook-grade GH ingress (poll stub only)
- Dev / QA / IaC / TaskGraph hires
- Auto-delete task rooms on Redis TTL
- Trajectory files in meta git
- Splitting F1–F9 across multiple product PRs

---

## Landed reference (condensed)

U1–U6 file plans executed: `gate_coach`, `delivery_voice`, `post_human_next`, land+sync, KB land+approve, PE↔PM settle, OKF context, human_replies. See git history PRs #21–#24 and as-built.

### Develop merge ledger (recent)

| PR | Summary |
|----|---------|
| #21 | Gate‑1 decision paper + global temp purge |
| #22 | GraphQL undraft before merge |
| #23 | U1–U6 helpful-army + clarification rally |
| #24 | KB land pre-approve + reopen Buzz gate |
| next | **F1–F9 Team floor (single PR)** |

---

## Later hires (unchanged north star)

dev / qa / iac / sre / obs · codegraph MCP · TaskGraph as hire when Impact-Map alone is insufficient for mutate tiers.
