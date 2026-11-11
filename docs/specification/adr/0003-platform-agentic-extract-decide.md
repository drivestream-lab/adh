# ADR 0003 — Platform agentic extract / decide (no regex SSOT)

- **Status:** Accepted — E1 greenfield train (`feature/e1-dev-yaml-greenfield`)
- **Date:** 2026-11-11
- **Context:** Hired roles (PM, PE, Dev, KB, …) must parse Hermes/Cursor cards and Lead replies the same way. Regex SSOT and per-programme extract dupes drift and block agentic prompting. Lead ops commands (`engg go`, `hire engg`, `resume`, `traj`, …) stay exact phrase families today, with a reserved hole to go agentic later.

## Decision

1. **Platform modules under `src/adh_agents/runtime/`**
   - `agentic_extract.py` — labeled lines (`key: value`), `##` heading sections, allow-list match, INIT/VF/PR URL helpers. **No regex.**
   - `agentic_decide.py` — prompt → extract → allow-list decide for catalogue outcomes / brief recommends. Shared by every hired role.
   - `lead_commands.py` — Lead ops commands via **exact phrase lists** + `normalize_reply`-style families. **`classify_lead_command_agentic` is the reserved hole** (returns `None` until product enables it).
2. **Dev (and every role) consumes runtime extract/decide** — delete local `labeled_extract` / `outcome_decide` dupes. RealWorld remains guinea pig only; no tenant/INIT hardcoding in programmes.
3. **Zero `re` / `re.compile` under `src/adh_agents/`** — string split / token scan / phrase lists only. Regex is not an SSOT for delivery parsing.
4. **Lead commands stay phrase-list today** — leave the agentic classify hole so we can flip without rewriting callers.

## Verify slate (RealWorld guinea pig)

| INIT | Lane | Mode |
|------|------|------|
| INIT-REALWORLD-001 | **Dev** engg (`workflow.yaml` development) | **god** |
| INIT-REALWORLD-002 | **Dev** engg | **human** (Lead manual from briefs) |
| INIT-REALWORLD-007 | **PM + PE** product lane | **god** |
| INIT-REALWORLD-008 | **PM + PE** product lane | **human** (Lead manual) |

## Consequences

- One extract/decide surface for all hires; programmes stay thin YAML / baton walkers.
- Lead phrase lists remain deterministic; agentic classify can land later behind the hole.
- Docs/as-built track the verify slate above (not ad-hoc INIT numbers).

## Non-goals

- Enabling agentic Lead classify in this cut.
- Reintroducing regex parsers under `adh_agents`.
- Hardcoding RealWorld INITs in programme code.
