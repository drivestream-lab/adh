# ADH Agents Team OS

## Intent

ADH runs a **software-engineering team of agents**. Buzz is the talking floor. The pinned delivery catalogue (`workflow.yaml`) says what stage comes next. Agents are hired **incrementally** into the tenant ops room. **ADH is the product**; tenant lanes (e.g. RealWorld) are guinea pigs to pressure-test the OS.

## Control plane (mandatory)

```text
#tenant-ops Buzz
        │
        ▼
┌───────────────────────────────┐
│  Orchestrator (runtime)       │  work store · ask-back · gates · resume · stop
│  programme runner registry    │
└───────────────┬───────────────┘
                │
     ┌──────────┼──────────┬─────────┐
     ▼          ▼          ▼         ▼
    PM         PE        read       kb   …later
```

- Every role **worker embeds** this plane (role-scoped Redis work units).
- Programmes **register**; they do not reimplement routing.
- Agents are thin: listen, identity, batons, forge ACL.

## Roles (incremental roster)

| Role | Buzz id | Owns | Hire / verify |
|------|---------|------|----------------|
| PM | `adh.pm` | Requirements → draft PRD PR; product answers; PRD merge | Verify first on new OS |
| Read | `adh.read` | Walk one repo; Buzz rollup | Before / with PE fan-out |
| PE | `adh.pe` | Gate‑1: fan-out reads, ≤10 Q / ≤4 rounds, attest, ping PM | After PM verify; consume `pe.review` |
| KB | `adh.kb` | Patch OKF `knowledge/` heads | After merge enrich |
| Dev / QA / IaC / SRE / Obs | later | … | later |

## Workers

```text
make adh-pm    → adh_pm_worker
make adh-pe    → adh_pe_worker
make adh-read  → adh_read_worker
make adh-kb    → adh_kb_worker
```

## Collaboration loop

```text
Buzz message or baton
  → role worker (role-scoped Orchestrator filter)
  → claim baton if needed (Redis idempotency)
  → programme runs with tools
  → Buzz rollup (+ forge under ACL)
  → catalogue / next gate continues
```

### Buzz UX (ops — no overload)

Ops is for **human input and next steps**, not evidence dumps.

| Field | Rule |
|-------|------|
| **What** | ≤3 lines BLUF |
| **Evidence** | Link / path / PR only |
| **Next** | One clear ask **or** “waiting on `{role}` / baton …” |
| **Tokens** | Only when a Lead gate is open |
| **Never** | Full walks, full diffs, raw forge JSON, multi-ask lists |

Heavy evidence lives in artefacts / PRs / OKF `knowledge/` heads. Progress ticks while working; one short DONE rollup.

## Graphs (do not conflate)

| Graph | SSOT | Use |
|-------|------|-----|
| Delivery work graph | `prayog-skills/workflow.yaml` | Stage navigation (ADR 0001) |
| Repo dependency DAG | Impact-Map (+ KB overlays) | Parallel mutate tiers; reads stay parallel |
| Code graph | Fleet / MCP tool | Inside reader only |

## KB heads (OKF in tenant meta)

`foundation/` · `stacks/` · `repos/` · `contracts/` — **no** `initiatives/` tree.  
See [`../references/adh-kb-heads.md`](../references/adh-kb-heads.md).

## Non-negotiables

1. Buzz = human trigger + agent collab surface (one ops room per tenant).
2. Specialists do not call each other in-process as SSOT — batons do.
3. Parallel sessions, TTL, ask-back, resume, stall-keep, retry are **OS** attributes.
4. Missing agent on a catalogue node → fail closed on Buzz.
5. Forge scoped per role.
6. **No legacy / dead code** carried beside the new tree.
7. **Buzz light** — BLUF + artefact pointer + single next step; no information overload.
8. **No tenant/INIT/repo hardcoding** in programmes — resolve via tenant context + baton payload (RealWorld is guinea pig only).

## Implementation

**Work tracker (follow this):** [`../plans/adh-agents-implementation-plan.md`](../plans/adh-agents-implementation-plan.md)  
**ADR:** [0002](../adr/0002-adh-agents-team-os.md) · **As-built:** [`../as-built/implementation-status.md`](../as-built/implementation-status.md)

Retired framing: “Hermes enabler + responsibility agents” **phase lists** that assumed a Hermes facade router. Enabler = `BaseHermesAgent`; control plane = Orchestrator in `adh_agents/runtime`.  
**Still binding from that north star:** recommend + artefact, human conversational gates, Buzz light, ports over hardcoding — see plan D3–D5 locks.
