# ADH Agents Team OS

## Intent

ADH runs a **software-engineering team of Hermes agents**. Buzz is the talking floor for humans and bots. The pinned delivery catalogue (`workflow.yaml`) is what stage comes next. Agents are hired **incrementally** into the tenant ops room (`#realworld-ops`, …) and enhanced over time (tools get smarter; baton contracts stay stable).

## Roles (incremental roster)

| Role | Buzz id (PoC) | Owns | Hire order |
|------|---------------|------|------------|
| PM | `adh.pm` | Requirements lane → draft PRD PR; product answers; PRD merge | **Live** (`PMAgent` on `BaseHermesAgent`, develop) |
| PE | `adh.pe` | Gate‑1: fan-out reads, ≤10 Q / ≤4 rounds, attest, ping PM merge | Next (Wave 0b) |
| Read | `adh.read` | Walk one repo with tools; Buzz rollup | 2 |
| KB | `adh.kb` | Patch OKF `knowledge/` heads when triggered | 3 |
| Dev | `adh.dev.*` | Implement / open app PRs by dependency-DAG tier | later |
| QA | `adh.qa` | Docker/local verify on PR → Buzz + GitHub | later |
| IaC / SRE / Obs | `adh.iac` / `adh.sre` / `adh.obs` | Platform / prove / monitoring | later |

## Collaboration loop

```text
Buzz baton (human or agent)
  → role worker claims (Redis idempotency)
  → agent works with tools
  → Buzz rollup (+ optional forge under ACL)
  → coordinator / catalogue continues
```

Same pattern for: PE→read digests, PE↔PM questions, PE attest, PM merge, KB enrich, and later **dev opens PR → QA verifies in docker → updates GitHub**.

## Graphs (do not conflate)

| Graph | SSOT | Use |
|-------|------|-----|
| Delivery work graph | `prayog-skills/workflow.yaml` | Stage navigation (ADR 0001) |
| Repo dependency DAG | Impact-Map (+ KB `contracts/` / topology overlays) | Parallel **mutate** work (dev tiers); reads stay parallel |
| Code graph | Fleet / MCP tool | **Inside** reader (optional); never the cross-repo scheduler |

## KB heads (OKF in tenant meta)

`foundation/` · `stacks/` · `repos/` · `contracts/` — **no** `initiatives/` tree.  
ADRs stay in app repos; KB holds maps, pointers, cross-cuts. See [`../references/adh-kb-heads.md`](../references/adh-kb-heads.md).

## Non-negotiables

1. Buzz remains human trigger + agent collab surface (one ops room per tenant).
2. Specialists do not call each other in-process as SSOT — batons do.
3. Tool upgrades (grep → codegraph MCP) must not break baton/rollup schema.
4. Missing agent on a catalogue node → fail closed on Buzz (no silent skip).
5. Forge scoped per role.

## Implementation

See [`../plans/adh-agents-implementation-plan.md`](../plans/adh-agents-implementation-plan.md) and [ADR 0002](../adr/0002-adh-agents-team-os.md).
