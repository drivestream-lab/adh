# INIT-STRATUM-HITL-WEB-001: Platform authoring UI (prd-think candidate)

| Field | Value |
|-------|-------|
| Initiative | INIT-STRATUM-HITL-WEB-001 |
| Status | candidate |
| Brief | Conversation + Figma Platform authoring page 04; planning `product-surface-pitch.md` / programme CORE outlines as context only |
| Existing PRD | none — prior process HITL-WEB-001 purged ([PR #49](https://github.com/Sandvik-Common/stratum-meta/pull/49)); not modified / not revived |
| Candidate path | `prd/reports/INIT-STRATUM-HITL-WEB-001-prd-think.md` |
| Visual SoT | [Figma `ui_v0.1` · 04 · Platform authoring (v0.3)](https://www.figma.com/design/3C0bG20lxaQ4Y9OAEkGELh/ui_v0.1?node-id=257-1955) |
| Delivery home | `stratum-hitl-web` (greenfield product UI; BFF consumer of `stratum-platform-core`) |
| Score | `/prd-quality` — not written by this skill |

## 1. Job and outcome

- **Job:** On greenfield `stratum-hitl-web`, people with different roles can log in and complete **Foundation Platform authoring** (Figma page 04) end-to-end against **current `stratum-platform-core`**, including the Open-pit ready gate through the **Situations stub (P31)** — integrating colleague-delivered **login** and **Unit** work rather than replacing it.
- **Why now:** Backend Foundation capabilities are already in place; without this FE INIT the product walk and Figma SoT stay non-executable in the portal.
- **If we do nothing:** platform-core exists but Platform authoring remains unreachable in product UI; design stays slides; login/Unit fragments do not become a complete authoring surface.
- **Kill assumption:** Fails if (1) page-04 screens are not treatable as close to the Figma SoT (integration-test alignment fixes allowed), or (2) the Open-pit Foundation ready walk cannot be completed against live platform-core (including existing login + Units), or (3) the UI invents Foundation truth instead of integrating the backend, or (4) role login does not enforce different capabilities.

## 2. Locked decisions

1. This INIT is a **product** Platform authoring UI PRD on greenfield `stratum-hitl-web` — **not** a revival of the purged process/warm-up HITL-WEB-001 ([PR #49](https://github.com/Sandvik-Common/stratum-meta/pull/49)).
2. **In scope = Platform authoring only** (Figma page 04 `P##` set, ~70+ frames). Situations / Model-run / Conformance / Running-model depth are out; **P31 Situations stub** is the handoff only.
3. UI **integrates current `stratum-platform-core`** as domain SSOT; frontend projects backend ViewModels — no second Foundation truth in the UI.
4. Visual SoT is [Platform authoring Figma](https://www.figma.com/design/3C0bG20lxaQ4Y9OAEkGELh/ui_v0.1?node-id=257-1955). Frames must stay **as close as possible**; **bug fixes and alignment during BE integration tests are expected and allowed**.
5. **Multi-role login is enforced:** session carries an acting role; unauthorized Foundation actions are blocked using backend privileges/clearance. Colleague **login** and **Unit API** UI already exist and must be **integrated/extended**, not discarded.
6. Full enterprise IdP + FIDO2 hard DoD is **not** required beyond what the existing login path already provides; demo persona / stub IdP remains acceptable for v1 if role enforcement still holds.
7. Backend Foundation behaviour (publish, pin, resolve, B+ store rules) remains owned by platform-core / CORE programme — this INIT owns the **product UI integration**, not re-specifying those domain rules.

## 3. In scope / non-goals

### In scope

- Greenfield Platform authoring UI for Figma page 04 screens (Prepare / Master data / Governance / Core taxonomy / Product scopes / Operating contexts / Releases / Workspaces / Promotions / P31 stub).
- High visual fidelity to the linked Figma page, with integration-test alignment fixes allowed.
- Integration to live platform-core for authoring, read, publish, pin, promotions, and privilege checks.
- Integrate and extend existing **login** and **Unit** FE work.
- Role-differentiated entry and enforced capability differences.

### Non-goals (load-bearing)

- Full Situations authoring, Model runs, Model Card / Conformance, fleets / telemetry / OTA (Figma pages 05–08 / CORE-002+ product depth).
- Inventing or owning Foundation domain rules, resolve, or publish truth in the frontend.
- Rebuilding the entire Figma Components library as a separate design-system package DoD (page-04 screens are the fidelity bar).
- Reviving purged HITL process warm-up / old portal debt ([PR #49](https://github.com/Sandvik-Common/stratum-meta/pull/49)).
- Production Entra + FIDO2 as a separate hard DoD beyond existing login (see lock 6).

## 4. Actors

| Actor | Can actually | Cannot / OQ |
|-------|----------------|-------------|
| Person with **Platform Architecture** (or equivalent authored role) | Log in; author page-04 Foundation surfaces permitted by privileges; complete Open-pit ready gate when clearance allows | Cannot bypass backend deny |
| Person with **other Foundation roles** (as authored in Roles / privileges) | Log in; perform only permitted actions; see acting role in shell | Cannot perform Architect-only actions when privileges forbid |
| Org / programme reviewer (may be a role) | Walk stakeholder-relevant page-04 paths for review/demo when permitted | Full Situations/SceneIQ authoring (non-goal) |
| Downstream author (preview) | Reach **P31 Situations stub** after pin when permitted | Full Situations product UI (later INIT) |
| FE / portal eng (delivery) | Integrate UI to platform-core; extend login/Unit | Not a product end-user of Foundation truth |

## 5. Capabilities

| ID | Capability | Journeys covered | Notes |
|----|------------|------------------|-------|
| CAP-01 | Role-aware authenticated entry into Platform authoring | J-01, J-08 | Integrates existing login |
| CAP-02 | Figma-faithful Platform authoring product surface (page 04) | J-02–J-07, J-01 | Visual SoT link in §1 table |
| CAP-03 | Prepare & governance authoring via platform-core | J-02, J-08 | Privileges, category kinds, roles, clearance |
| CAP-04 | Core taxonomy & units authoring via platform-core | J-03 | Extends existing Unit integration |
| CAP-05 | Product scope authoring via platform-core | J-04 | Open-pit cast vocabulary |
| CAP-06 | Operating context authoring via platform-core | J-05 | Field groups + permitted bands |
| CAP-07 | Foundation release publish & workspace pin via platform-core | J-06 | Create-then-pin path |
| CAP-08 | Promotions decide/qualify/accept UI via platform-core | J-07 | Page-04 promotions only |
| CAP-09 | Open-pit ready gate handoff to Situations stub | J-06 | P31 only |
| CAP-10 | Fail-closed backend integration behaviour | J-09, J-08 | No silent fake success |

## 6. Requirements

| ID | CAP | Requirement (WHAT) | Condition / event | Observable result | Evidence |
|----|-----|--------------------|-------------------|-------------------|----------|
| REQ-01 | CAP-01 | A person can authenticate into the Platform authoring experience with an acting role | Valid credentials / allowed demo persona for an authored role | Session shows the acting role; Foundation shell is reachable | live J-01 · CAP-01 |
| REQ-02 | CAP-01 | Unauthorized Foundation actions are blocked for the acting role | Authenticated session whose privileges forbid the action | Action is not completed; user receives a clear denied/unavailable outcome; backend deny is respected | live J-08 · CAP-01 |
| REQ-03 | CAP-02 | Page-04 Platform authoring screens match the Figma visual SoT as closely as practicable | Screen is in the page-04 `P##` delivery set | Layout, hierarchy, labels, and primary interaction beats are recognizably the same as Figma; documented alignment fixes from BE integration tests are allowed | inspection CAP-02 · live J-06 |
| REQ-04 | CAP-02 | Visual SoT for this INIT is the Platform authoring Figma page | Design or implementation review of page-04 UI | Reviewers can open [Figma node `257:1955`](https://