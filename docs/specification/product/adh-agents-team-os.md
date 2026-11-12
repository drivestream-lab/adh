# ADH Agents Team OS

## Intent

ADH is a **delivery harness**: it understands the pinned delivery workflow (`workflow.yaml`)
and **orchestrates automation** across a hired agent army. Buzz is the talking floor
(Cursor-like durable chat). Agents are hired **incrementally** into the tenant **hub**,
then collaborate in **per-task rooms**.

**Tasks are first-class.** Every bound work item is a durable Postgres row
(`buzz_tasks`) with a **kind** (`init` | `bug` | `enhancement` | …) and a **state**
(`bound` → `running` → `gated` → `done` / `halted` → `archived`). Resume and
orchestration key off **task + catalogue + trajectory** — never by replaying the
whole Buzz transcript. **ADH is the product**; tenant lanes (e.g. RealWorld) are
guinea pigs to pressure-test the OS.

## Storage (locked)

| Store | Holds | Does **not** hold |
|-------|--------|-------------------|
| **Postgres (Buzz)** | Identities, hub + task rooms, members, messages, tasks, archive metadata, **`buzz_task_events` trajectory** | Ephemeral gate machines |
| **Redis** | Live control plane: work sessions, batons, presence, short god-mode chain ledger | Chat history, archive, trajectory SSOT |
| **Disk/git meta** | PRD, reports, OKF `knowledge/` heads | Buzz transcript |

**Postgres is the durable product chat** (long retention; archive hides, delete is explicit).  
**Redis is live OS only** (TTL OK). **Never force-fit chat into Redis.**

| Redis key family | Default TTL |
|------------------|-------------|
| Work sessions (`adh:agent:work:…`) | **7d** (refresh on save) |
| Batons | **1d** |
| Presence / god-chain | short |

Hermes/ledger Postgres DBs remain secondary (not Team OS task SSOT).

## Control plane (mandatory)

```text
#tenant-hub  (+ non-archived task + engg rooms)
        │
        ▼
┌───────────────────────────────┐
│  Orchestrator (runtime)       │  work store · ask-back · gates · GateOpener · resume · stop
│  programme runner registry    │
└───────────────┬───────────────┘
                │
     ┌──────────┼──────────┬─────────┬────────┐
     ▼          ▼          ▼         ▼        ▼
    PM         PE         Dev      read      kb   …later
```

- Every role **worker embeds** this plane (role-scoped Redis work units).
- Programmes **register**; they do not reimplement routing.
- Agents are thin: listen, identity, batons, forge ACL, CollabPost.
- Workers subscribe to the **hub + non-archived task homes + engg floors** for the tenant.

## Rooms (hub + task + programme floors)

**Scale vantage:** many delivery units × many programmes. Hub = portfolio radar; `#task-<id>` = unit home; split **programme floors** when a stage is long, parallel, or ownership-hostile (first: engg-think).

```text
#{tenant}-ops          HUB — intake + announces + traj radar
#task-{TASK_ID}        TASK HOME — product lane (PM / PE Gate‑1 / KB)
#engg-{TASK_ID}        ENGG FLOOR — Dev YAML development lane (E1)
```

### Mental model (do not shuttle)

| | **Hub** `#{tenant}-ops` | **Task home** `#task-{TASK_ID}` | **Engg floor** `#engg-{TASK_ID}` |
|--|-------------------------|----------------------------------|----------------------------------|
| Role | Portfolio radar / intake | Product collaboration | Engg-think programme |
| Lifetime | Always on | Born at bind; archive when product done | Opened by **PE→Dev**; archive independently |
| Lead habit | Skim traj / post new outlines | Live PM/PE/KB work | Live Dev gates (`accept deps`…) |

**Hub holds:**
- Ingress: Lead outline, GH bind announce, hire/presence stalls
- One-line lifecycle + **Buzz-light traj mirrors**
- Lead **detailed traj card** (`traj` / `traj <id>`) — **not** in task/engg rooms

**Task home holds (product programmes):**
- Authoring / meta-PM / PE Gate‑1 / PE↔PM rally / merge / KB
- Done coach for product phase

**Engg floor holds (Dev programme):**
- Spec draft → spec PR → feasibility / tech review → plan / WM → coding-ready → spec merge → board seed (YAML)
- Opened when **PE emits** `dev.engg_think` (Lead hire = escape hatch only)

**Code rule:** baton `ops_room` = **owning collaboration room** for that hop (task home for PE/KB; **engg floor for Dev**) — **not** the hub. Hub must not accumulate still-working / baton spam.

| Kind | Ingress | Task id |
|------|---------|---------|
| `init` | Buzz outline on hub | `INIT-…` |
| `bug` / `enhancement` | GitHub issue/board (opt-in label; bind API + poll stub) | `BUG-…` / `ENH-…` |

Canonical task row lives in **Postgres** (`buzz_tasks`). Unique `(tenant, source_ref)` for GH. No Redis Task SSOT.

| Task state | Meaning |
|------------|---------|
| `bound` | Task + room created; not yet advancing catalogue |
| `running` | Army/catalogue hops in progress |
| `gated` | Soft gate open (Lead token or god recommend) |
| `done` | Delivery complete; archive coach pending |
| `halted` | God/mode halt or fail-closed stop |
| `archived` | Lead archived (history kept) |

Redis work sessions / batons are the **live projection** of that task — they must not
become a second task SSOT.

## Two harnesses (normative)

| Harness | SSOT | Job |
|---------|------|-----|
| **Delivery** | `workflow.yaml` + prayog skills + forge ACL | Produce artefacts; GitHub; predicates |
| **Behaviour** | `src/prompts/hermes.{role}.*` via PromptService | Mimic human judgment — questions, ADR/TDD/impact review, recommend |

Skills without behaviour packs = pipeline with token gates.  
Behaviour packs without skills = reviewer with no delivery teeth.  
Both required. See [ADR 0004](../adr/0004-hermes-behaviour-harness.md) + [behaviour plan](../plans/hermes-behaviour-harness-plan.md).  
**Greenfield:** no inline judgment prompts; delete dual paths in-wave. Knowledge closes the evolution loop (Mode A inject → Mode B Lead-gated prompt PRs later).

## Roles (incremental roster)

| Role | Buzz id | Owns | Hire / verify |
|------|---------|------|----------------|
| PM | `adh.pm` | Requirements → draft PRD PR; product answers; PRD merge | Verify first on new OS; `hermes.pm.*` gold |
| Dev | `adh.dev` | YAML `development` lane after PRD merge: spec → spec PR → review/plan → merge → board | E1 landed; behaviour packs wave B1 |
| Coder | `adh.coder` (later) | Execute board/WorkManifest → code PRs | After Dev fence |
| Read | `adh.read` | Walk one repo; Buzz rollup | Before / with PE fan-out |
| PE | `adh.pe` | Product review: fan-out reads, ≤10 Q / ≤2 agent rounds, attest, ping PM | Behaviour packs wave B2 |
| KB | `adh.kb` | Patch OKF `knowledge/` heads; feed next-hop `kb_excerpt` | After merge enrich; loop Mode A in B3 |
| QA / IaC / SRE / Obs | later | … | later |

## Workers

```text
make adh-pm    → adh_pm_worker
make adh-pe    → adh_pe_worker
make adh-read  → adh_read_worker
make adh-kb    → adh_kb_worker
make adh-dev   → adh_dev_worker   # E1 engg think → board
```

## Collaboration loop

```text
Ingress (outline | GH bind) → Postgres task + task room
  → baton claim (Redis NX) + CollabPost on Buzz (@role)
  → programme runs with tools
  → GateOpener (human wait | god plays recommend)
  → trajectory row in buzz_task_events
  → land / sync / purge temps (disk) / archive coach
```

Batons remain handoff **SSOT**. Buzz CollabPosts are the **visible** army talk. Specialists do not call each other in-process as SSOT.

### Buzz UX

**Ingest ack (base premise):** every consumed Lead/human message gets an immediate  
`Got it — working on \`…\`.` (`payload.status=received`) **before** long work  
(`still_working` / forge / Cursor). Lead must never wonder if the bot saw the post.  
**Helpful army** (working role → Lead gate): I did / recommend / evidence / outside ADH / exact tokens.  
**CollabPost** (agent → agent): short `@adh.pe`-style lines on baton emit/claim/done.  
**UI:** open on latest; load **last 20** messages; scroll-up paginates older from Postgres; SSE appends with stick-to-bottom. Desktop (`apps/buzz-desktop`) only — no dual web UI.

Heavy evidence lives in artefacts / PRs / OKF heads. Temp papers under `prd/reports/` are ephemeral (**purge = delete**). Buzz **archive ≠ purge**: archive hides the task room; messages remain until Lead **delete task**.

### Clarification rally (U6)

PE↔PM agent rally (≤2 rounds); no mid-rally human ack. Human (or god mode) only after settle — merge / park. OKF heads feed prompts.

### God mode + trajectory

| Mode | Gate close |
|------|------------|
| `human` (default) | Lead Buzz token |
| `god` (`ADH_AUTONOMY_MODE=god`) | Hermes `brief.recommend` ∈ reply_tokens via GateOpener; Lead ignored for open gates |

Halt tokens / bad recommend → `god_mode_halt` (no human rescue wait). `delete task` / `discard local` never auto in god without an explicit allow flag.  
**Trajectory:** append-only `buzz_task_events` in Postgres (gate_open / god_taken / god_halt / baton / land / archive / rewind / rewind_denied). **No trajectory artefacts in meta git.** Lead may post `traj` on Buzz for a kind | purpose | token | who card.

### Human rewind (H1)

Human mode only. Lead posts `rewind` → coach always shows **Can / Cannot / Outside ADH** → `rewind N` + `reason:` → **`confirm rewind`**. God and post–product-merge → `rewind_denied` (git undo outside ADH). Open draft PRs we raised are closed when rewind crosses that fence. Purge follows the temp-paper matrix (`start` purges all thinks; promote re-pick keeps thinks; PRD kept until next promote overwrite). Same task room on `start` (paste outline again).

## Graphs (do not conflate)

| Graph | SSOT | Use |
|-------|------|-----|
| Delivery work graph | `prayog-skills/workflow.yaml` | **SSOT** stage navigation (ADR 0001) — PM + Dev engg |
| Repo dependency DAG | Impact-Map (+ KB overlays); skills refine during development hops | Scope repos for spec / plan / board waves |
| Task DAG | Plan §9 WorkManifest | Board seed + coder executes TASK* |
| Code graph | Fleet / MCP tool | Inside reader / skills only |

### Dev engg lane (E1) — greenfield

**SSOT:** `workflow.yaml` `development` entry — **same rule as PM lane**. No invented ADH-only hops (no `deps-acceptance` programme stage).

**PE → Dev** baton after product fence (`prd-merge` / merged PRD OK). PM does **not** start Dev. Floor: **`#engg-<id>`**.

**Spine (YAML `pass`):**  
`spec-draft` → `spec-pr-action` → `initiative-feasibility` → `spec-technical-review` → `technical-review-approval` → `spec-implementation-plan` → `coding-readiness` → `spec-merge` → `board-tickets-action`.

Skills + forge use **PRD + impacted codebases** (`commit_workspace` as declared). GateOpener on YAML human-checkpoints only. **God must auto-progress** (including same-purpose re-entry / `another round` within cap).

**Verify slate (after rewrite):**

| INIT | Lane | Mode | Notes |
|------|------|------|-------|
| INIT-REALWORLD-001 | Dev engg | **god** | PRD [#5](https://github.com/drivestream-lab/realworld-meta/pull/5) |
| INIT-REALWORLD-002 | Dev engg | **human** | PRD [#8](https://github.com/drivestream-lab/realworld-meta/pull/8); Lead plays YAML checkpoints |
| INIT-REALWORLD-007 | PM + PE | **god** | Product lane autopilot |
| INIT-REALWORLD-008 | PM + PE | **human** | Lead manual from briefs |

Prior `#engg-init-realworld-001` wiped. **Coder** later. Lead ops cmds = phrase lists + `normalize_reply` (agentic hole reserved — [ADR 0003](../adr/0003-platform-agentic-extract-decide.md)).

## KB heads (OKF in tenant meta)

`foundation/` · `stacks/` · `repos/` · `contracts/` — **no** `initiatives/` tree.  
See [`../references/adh-kb-heads.md`](../references/adh-kb-heads.md).

## Non-negotiables

1. Buzz = durable hired-team messaging floor (hub + task rooms); Postgres SSOT for chat.
2. Batons = agent handoff SSOT (Redis); CollabPosts make hops visible on Buzz.
3. Redis = live control plane only — never chat/archive/trajectory SSOT.
4. Missing agent on a catalogue node → fail closed on Buzz.
5. Forge scoped per role.
6. **No legacy / dead code** / dual paths beside the new tree.
7. **Buzz light** — coach + CollabPost + pointers; no evidence dumps.
8. **No tenant/INIT/repo hardcoding** in programmes — tenant context + baton/task payload (RealWorld = guinea pig).
9. **Agentic + conversational** — understand→catalogue; soft gates wait in human mode; god mode plays recommend only.
10. Temp papers ephemeral (delete). Buzz archive retains history; delete is Lead-explicit.
11. Helpful army + GateOpener for all human-shaped gates.
12. Agent↔agent clarification; human/god after briefs settle.
13. Trajectory in `buzz_task_events` only — never meta repo files for autopilot journals.
14. **Ingest ack first** — on every consumed Lead message, post `Got it — working on …` before long hops; silence after a human post is a bug.
15. **Delivery harness** — maintain `buzz_tasks` **kind + state**; orchestrate from workflow + task SSOT + trajectory, not chat archaeology.
16. **Trajectory** — SSOT `buzz_task_events`; **Buzz-light mirror on ops**; Lead **detailed traj card on ops** (never task/engg dump). God mode: forward-only (no rewind).
17. **Ingress** — outline → `init` only; `bug`/`enhancement` → GitHub ticket only.
18. **Hub → task** — guarded desktop auto-switch when Lead is on hub; never steal focus from another task room.

## Implementation

**Work tracker (follow this):** [`../plans/adh-agents-implementation-plan.md`](../plans/adh-agents-implementation-plan.md)  
**ADR:** [0002](../adr/0002-adh-agents-team-os.md) · **As-built:** [`../as-built/implementation-status.md`](../as-built/implementation-status.md)

Enabler = `BaseHermesAgent`; control plane = Orchestrator in `adh_agents/runtime`.  
**Next:** E1 **greenfield** Dev rewrite + platform extract/decide; verify **001/002** (Dev) and **007/008** (PM+PE); coder hire later.
