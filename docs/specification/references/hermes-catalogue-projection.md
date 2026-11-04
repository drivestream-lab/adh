# Hermes catalogue projection

How ADH projects the pinned Prayog workflow into runtime types. **Source of truth:** `prayog-skills/workflow.yaml` + `delivery-contract.yaml`. ADH must not invent a parallel graph.

## Inputs

| Input | Role |
|-------|------|
| `.harness-pin.yaml` | Pin record (`agent_skills.ref`, profile, contract) |
| `prayog-skills/workflow.yaml` | Nodes, entrypoints, outcomes, forge blocks |
| `prayog-skills/skills/**/SKILL.md` | Skill id + description index |
| `prayog-skills/delivery-contract.yaml` | Outcomes vocabulary, dispatch policy, principles |

## Projection

| Workflow field | Hermes use |
|----------------|------------|
| `entrypoints.*` | Programme start nodes (e.g. meta-pm → validate-requirements) |
| `nodes.*.type` | Dispatch branch: skill / human-checkpoint / external-action / decision / terminal |
| `nodes.*.outcomes` | `resolve(stage, outcome) → next_id` |
| `nodes.*.purpose` | Checkpoint display / brief purpose (string from YAML) |
| `nodes.*.dispatch` | Orchestrator auto-dispatch eligibility (`manual` default) |
| `nodes.*.authorization` | Whether Lead must explicitly authorize forge |
| `nodes.*.forge` | Forge action + requires/labels — executed only when authorized |
| Skill frontmatter `name` | Skill hop id for the runner |

## Forbidden in ADH

- Python enums / frozensets of skill ids, hop names, or Lead start phrases as SSOT
- Hardcoded “validate → update → impact” graphs parallel to workflow outcomes
- Auto-transition of `type: human-checkpoint`

## Resolve algorithm (same as delivery-contract)

```text
next_id = catalogue.nodes[stage].outcomes[outcome]
next = catalogue.nodes[next_id]
# if next.type == human-checkpoint → STOP for Lead judgment
# if orchestrator_auto and next.type == skill and dispatch != orchestrated → STOP
```
