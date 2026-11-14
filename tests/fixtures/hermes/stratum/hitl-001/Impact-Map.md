---
schema_version: 1
initiative: INIT-STRATUM-HITL-WEB-001
map_revision: 1
source_prd: prd/INIT-STRATUM-HITL-WEB-001.md
source_prd_digest: sha256:18ff1e8c74c4d9a7a056d27dd3974ca451695ddcbfc695f53bda8b46e6ce87c8
previous_revision: null
previous_artifact_commit: null
change_reason: initial map after gate-first PRD promote + Resolution CHG-01–04 + incremental validate pass (report_revision 2)
material_change: true
generated_at: 2026-09-15T08:30:00Z
---

# Impact map — INIT-STRATUM-HITL-WEB-001 — revision 1

> This file is generated locally before PR creation and becomes the scope source
> of truth when committed. Effective approval is derived from a tech-lead
> GitHub APPROVED review on the exact current meta PR head SHA; dynamic PR state
> is not stored in this artifact's frontmatter.

## 1. Source and revision

| Field | Value |
|-------|-------|
| PRD | `prd/INIT-STRATUM-HITL-WEB-001.md` |
| PRD digest | `sha256:18ff1e8c74c4d9a7a056d27dd3974ca451695ddcbfc695f53bda8b46e6ce87c8` |
| Map revision | `1` |
| Previous revision | none |
| Previous artifact commit | none |
| Change reason | Initial map for greenfield Platform authoring UI (Figma page 04 / C7 gate-first) on `stratum-hitl-web`. Validation `report_revision` 2 — 0 open product findings (VF-05 Stage4/6 accepted skip). |
| Material change | yes — first map for this reclaimed greenfield initiative |

### T0 identity (completed)

| Field | Value |
|-------|-------|
| Collision detection | `unrelated` (historical id reuse) → treat as clear to map |
| Human resolution | none |
| Evidence | No `Impact-Map-INIT-STRATUM-HITL-WEB-001*`. No open PR on branch `chore/INIT-STRATUM-HITL-WEB-001-prd-think`. Merged [#19](https://github.com/Sandvik-Common/stratum-meta/pull/19) was **process warm-up** HITL-WEB-001; [#49](https://github.com/Sandvik-Common/stratum-meta/pull/49) purged that INIT and reclaimed the id. Current PRD non-goal explicitly rejects revival of purged process artefacts. Open [#48](https://github.com/Sandvik-Common/stratum-meta/pull/48) is **INIT-STRATUM-PLATFORM-CORE-001** (backend sibling dependency), not a duplicate FE PRD. Closed #18/#20 are prior HITL warm-up/ODD UI — not this greenfield page-04 gate. |
| External action authorized | false |

```yaml
identity_collision:
  detection: unrelated
  evidence:
    - no Impact-Map-INIT-STRATUM-HITL-WEB-001
    - no open PR for chore/INIT-STRATUM-HITL-WEB-001-prd-think
    - merged #19 warm-up HITL-WEB-001 purged by #49; id reclaimed for greenfield FE
    - open #48 is PLATFORM-CORE-001 backend sibling, not duplicate initiative
  recommended_resolution: null
  human_decision: none
  external_action_authorized: false
```

### Capability areas (T1)

| Area | PRD refs | Notes |
|------|----------|-------|
| Existing-login entry + acting role | CAP-01, REQ-01, REQ-02, J-01, J-11 | Reuse colleague login; role deny |
| Figma-faithful Platform authoring chrome | CAP-02, REQ-03, REQ-04, REQ-15, J-01–J-09 | Visual SoT page 04; integration fixes allowed |
| Open-pit ready gate (acceptance) | CAP-03, REQ-05, J-02–J-08 | C7 on live platform-core → P31 stub |
| Gate-path taxonomy & units | CAP-04, REQ-06, J-03 | Extends Unit baseline |
| Gate-path scope & operating context | CAP-05, REQ-07, REQ-08, J-04, J-05 | Mobile perception + Open-pit mobile |
| Publish & create-then-pin | CAP-06, REQ-09, REQ-10, J-06 | Success only on backend confirm |
| Gate-path promotions | CAP-07, REQ-11, J-08 | Only beats C7 needs |
| P31 Situations stub | CAP-08, REQ-12, J-07 | CORE-002 boundary; no Situations depth |
| Page-04 beyond gate | CAP-09, REQ-13, J-09 | In scope; polish may trail |
| Fail-closed integration | CAP-10, REQ-14, J-10, J-11 | No fake success |
| Contracts (consumer) | CTR-01–CTR-05 | Auth/role, Foundation VMs, units, publish/pin, promotions |

## 2. Affected repositories

| Service | Repo | Team | Scope summary | Scope digest | Spec to create | Confidence |
|---------|------|------|---------------|--------------|----------------|------------|
| stratum-hitl-web | Sandvik-Common/stratum-hitl-web | @Sandvik-Common/stratum-frontend-devs | Greenfield Platform authoring UI on page-04 Figma SoT: reuse existing login and Unit baseline; C7 Open-pit ready gate on live platform-core through P31 Situations stub; gate-path taxonomy scope context publish pin promotions; fail-closed; role deny; page-04 frames beyond gate in scope with polish may trail; consumer of CORE-001 ViewModels only | `sha256:345687ab2588a8d3ef49a9f9d1eb2e2f500db0949e87e836fe6309cd54eff3ff` | `INIT-STRATUM-HITL-WEB-001-hitl-web.md` | High |

**H2 payload (canonical UTF-8/LF, exactly one trailing newline):**

```text
repo=Sandvik-Common/stratum-hitl-web
status=affected
capabilities=CAP-01,CAP-02,CAP-03,CAP-04,CAP-05,CAP-06,CAP-07,CAP-08,CAP-09,CAP-10,REQ-01,REQ-02,REQ-03,REQ-04,REQ-05,REQ-06,REQ-07,REQ-08,REQ-09,REQ-10,REQ-11,REQ-12,REQ-13,REQ-14,REQ-15
contracts=CTR-01,CTR-02,CTR-03,CTR-04,CTR-05
depends_on=Sandvik-Common/stratum-platform-core
scope=Greenfield Platform authoring UI on page-04 Figma SoT: reuse existing login and Unit baseline; C7 Open-pit ready gate on live platform-core through P31 Situations stub; gate-path taxonomy scope context publish pin promotions; fail-closed; role deny; page-04 frames beyond gate in scope with polish may trail; consumer of CORE-001 ViewModels only
```

**Catalog match:** `stratum-hitl-web` is the live Next.js reviewer/authoring console (Foundation, Situation, Model-run review). This INIT builds the **Platform authoring** surface (Figma page 04) as greenfield product UI consuming `stratum-platform-core` ViewModels — matching delivery home and BFF consumer role in the PRD.

## 3. Deferred repositories

| Service | Repo | Reason | Revisit condition |
|---------|------|--------|-------------------|
| stratum-platform-core | Sandvik-Common/stratum-platform-core | FE INIT does not implement Foundation domain SSOT; gate-path APIs/ViewModels are **CORE-001** (PRD lock 10). This map does not open a platform-core eng spec for HITL-WEB-001. | CORE-001 gaps vs C7 (A-01 / OQ-01) require backend follow-up; or product locks FE-driven API change |
| stratum-iac-infra | Sandvik-Common/stratum-iac-infra | No new substrate product capability; existing HITL hosting assumed | New ingress/env for Platform authoring beyond current HITL deploy |
| stratum-edge-agent | Sandvik-Common/stratum-edge-agent | No on-device / OTA / edge authoring in this INIT | Fleet or edge UI stories later |

## 4. Transitively affected repositories

Catalog YAML has **no** `depends_on` edges. PRD contract chain:

| Service | Repo | Depends on | Potential impact | Disposition |
|---------|------|------------|------------------|-------------|
| stratum-hitl-web | Sandvik-Common/stratum-hitl-web | stratum-platform-core (ViewModels / BFF) | Primary implementation; blocked on gate-path API readiness for REQ-05 | **affected** |
| stratum-platform-core | Sandvik-Common/stratum-platform-core | — (provider) | Must expose gate-path ops for acceptance; work owned by CORE-001 | **monitor** (deferred for this INIT) |
| stratum-edge-agent | Sandvik-Common/stratum-edge-agent | platform-core (elsewhere) | No FE authoring impact | not affected |
| stratum-iac-infra | Sandvik-Common/stratum-iac-infra | runtime substrate | No Phase 1 change | deferred |

## 5. Not affected

| Service | Repo | Reason |
|---------|------|--------|
| stratum-edge-agent | Sandvik-Common/stratum-edge-agent | Catalog: device OTA/telemetry. PRD non-goals: no Situations/Model-run/fleet depth; no edge UI. |
| stratum-iac-infra | Sandvik-Common/stratum-iac-infra | No Terraform/product infra capability in this PRD. |
| stratum-meta | Sandvik-Common/stratum-meta | Control-plane host for this PRD/map PR only — not an app implementation target. |
| stratum-platform-core | Sandvik-Common/stratum-platform-core | Catalog: Foundation authoring **service**. In-scope as **provider dependency** (CORE-001), not as an eng delivery target of this FE INIT. Listed under Deferred / monitor. |

**Sibling / external (not catalog implementation targets for this INIT):**

| Party | Role | Track via |
|-------|------|-----------|
| `INIT-STRATUM-PLATFORM-CORE-001` | Backend Foundation slice (publish/pin/taxonomy/scope/context) | Lock 10, A-01, open meta [#48](https://github.com/Sandvik-Common/stratum-meta/pull/48) |
| Figma `ui_v0.1` page 04 | Visual SoT | REQ-03, REQ-04, OQ-01 / OQ-03 |
| CORE-002 / Situations | Beyond P31 stub | CAP-08 boundary |

## 6. Cross-repository contracts

| Contract ID | Provider repo | Consumer repo | Capability | Owner | Status |
|-------------|---------------|---------------|------------|-------|--------|
| CTR-01 | Sandvik-Common/stratum-platform-core | Sandvik-Common/stratum-hitl-web | Authenticate + acting role / privileges — CAP-01, REQ-01, REQ-02 | platform + frontend | **changed** product use (Platform authoring entry); reuse existing login session model |
| CTR-02 | Sandvik-Common/stratum-platform-core | Sandvik-Common/stratum-hitl-web | Gate-path Foundation read/write ViewModels — CAP-03–CAP-05, REQ-05–REQ-08 | platform (CORE-001) + frontend | **new** FE consumption of CORE-001 VMs |
| CTR-03 | Sandvik-Common/stratum-platform-core | Sandvik-Common/stratum-hitl-web | Unit / unit-family on gate path — CAP-04, REQ-06 | platform + frontend | **unchanged** APIs; **extend** existing Unit UI baseline |
| CTR-04 | Sandvik-Common/stratum-platform-core | Sandvik-Common/stratum-hitl-web | Publish release; pin workspace; pin contents — CAP-06, REQ-09, REQ-10 | platform + frontend | **new** FE gate-path consumption |
| CTR-05 | Sandvik-Common/stratum-platform-core | Sandvik-Common/stratum-hitl-web | Promotion decide on gate-required items — CAP-07, REQ-11 | platform + frontend | **new** FE consumption when C7 requires |

No new catalog-to-catalog **provider** work in this INIT beyond consuming CORE-001.

## 7. Dependency and build order

```text
INIT-STRATUM-PLATFORM-CORE-001  (gate-path ViewModels / API — lock 10; meta PR #48)
        ↓
Sandvik-Common/stratum-hitl-web  (INIT-STRATUM-HITL-WEB-001 — Platform authoring UI / C7 gate)
        ↓ (boundary only)
CORE-002 / Situations depth     (out of scope; P31 stub only)
```

| Repo | Depends on | Reason |
|------|------------|--------|
| Sandvik-Common/stratum-hitl-web | Sandvik-Common/stratum-platform-core (CORE-001 surface) | UI projects ViewModels; REQ-05 live gate; CTR-01–CTR-05 |
| Sandvik-Common/stratum-platform-core | — | Deferred for this INIT; owned by CORE-001 |
| Sandvik-Common/stratum-edge-agent | — | Not affected |
| Sandvik-Common/stratum-iac-infra | — | Deferred |

**Engineering merge order:** After Gate 1 `impact-map-lgtm` on this meta PR, open **hitl-web** product spec only (`INIT-STRATUM-HITL-WEB-001-hitl-web.md`). Do **not** open platform-core / edge / iac eng specs under this INIT. Coordinate acceptance with CORE-001 availability (A-01 / IM-2); FE must not fake mutations if APIs missing (OQ-04).

## 8. Revision diff

Omit — map revision 1 (no prior Impact-Map artifact).

## 9. Downstream ripple ledger

No prior map revision repositories. Seed ledger for this revision:

| Repo | In-flight artifact | Required action | Reason | Owner | Blocking |
|------|--------------------|-----------------|--------|-------|----------|
| Sandvik-Common/stratum-hitl-web | none (login + Unit baseline exist in app) | open | After Gate 1 `impact-map-lgtm` on matching meta PR head | stratum-frontend-devs / PE | no (gate closed until LGTM) |
| Sandvik-Common/stratum-platform-core | CORE-001 meta [#48](https://github.com/Sandvik-Common/stratum-meta/pull/48) | hold | Deferred for this INIT; monitor CORE-001 for A-01 | stratum-platform-devs | no for Draft PR |
| Sandvik-Common/stratum-edge-agent | none | hold | Not affected | stratum-platform-devs | no |
| Sandvik-Common/stratum-iac-infra | none | hold | Deferred | stratum-pe-team | no |

## 10. Open questions

| ID | Lane | Question | Owner | Blocking | Required by | Default if deferred | Status |
|----|------|----------|-------|----------|-------------|---------------------|--------|
| IM-1 | PM | OQ-01: Exact C7 screen list vs full `P##` inventory for gate-critical REQ-05 | PM + design | **yes** for spec-draft done criteria | spec-draft | Use Figma Flow/C7 card list; PM signs gate subset | open |
| IM-2 | PE | A-01: PE confirms platform-core API surface vs C7 before spec-draft | PE | **yes** before Gate 1 sign-off if unconfirmed | before hitl-web spec assumes live ops | Extend OQ-01 or OQ-04 hide/disable — never fake | open |
| IM-3 | PE | Coordinate eng timing with open CORE-001 meta [#48](https://github.com/Sandvik-Common/stratum-meta/pull/48) | PE + Platform | no for Draft PR | feasibility / merge order | Hitl-web spec cites CORE-001 dependency; hide missing hooks | open |
| IM-4 | PM | OQ-02: Which promotion beats mandatory on v1 gate | PM | no | live J-08 | Only promotions C7 prototype traverses | open |
| IM-5 | PM | OQ-03: Acceptance owner for “looks like Figma” on gate path | PM | no | inspection REQ-03 | Product + FE joint C7 side-by-side | open |
| IM-6 | PM + PE | OQ-04: Non-gate `P##` without BE hook — hide vs visual-only | PM + PE | no | spec-draft | **Hide/disable** — never fake mutation | open |

> **Gate 1:** IM-1 / IM-2 block coding-readiness / PE LGTM until resolved or deferred with defaults above. Draft meta PR may proceed.

## 11. PR readiness handoff

| Item | Value |
|------|-------|
| Verdict | **PR READY** |
| Collision detection | unrelated (historical warm-up #19 purged by #49; id reclaimed) |
| Collision evidence | No Impact-Map; no open PR on think branch; #48 is CORE-001 sibling |
| Human resolution | none |
| Resolution completed | n/a |
| Existing PR | none |
| Proposed branch | `chore/INIT-STRATUM-HITL-WEB-001-prd` |
| Proposed base | `develop` |
| Proposed title | `[INIT-STRATUM-HITL-WEB-001] PRD — Platform authoring UI (gate-first)` |
| Files to commit | `prd/INIT-STRATUM-HITL-WEB-001.md`, this impact map, `prd/reports/Validation-Report-INIT-STRATUM-HITL-WEB-001.md`, `prd/reports/Resolution-INIT-STRATUM-HITL-WEB-001.md`, `prd/reports/Update-Summary-INIT-STRATUM-HITL-WEB-001.md`, think/quality reports (`*-prd-think*.md`, `*-prd-think-2.md`, `*-prd-quality.md`) |
| Reviewer | @Sandvik-Common/stratum-pe-team |
| Initial Gate 1 label | `impact-map-pending` |
| Additional invalidation label | none |
| Blocking items | none for Draft PR; IM-1 blocks spec-draft closure; IM-2 blocks Gate 1 if A-01 unconfirmed |

**No GitHub side effects have occurred.** Ask the user whether to create the Draft PR (`/open-draft-pr` after `/commit-workspace`). Continue only after explicit authorization.

### Proposed Draft PR body

```markdown
## Product change

Greenfield **Platform authoring** UI on `stratum-hitl-web` that looks like Figma page 04 and completes the **Open-pit Foundation ready gate (C7)** on live `stratum-platform-core` through the **P31 Situations stub** — reusing existing login and Unit baseline; UI does not invent Foundation truth.

## Impact-map summary

- Revision: 1
- PRD digest: `sha256:18ff1e8c74c4d9a7a056d27dd3974ca451695ddcbfc695f53bda8b46e6ce87c8`
- Affected repos: Sandvik-Common/stratum-hitl-web
- Deferred repos: stratum-platform-core (CORE-001 provider), stratum-iac-infra, stratum-edge-agent
- Blocking questions: IM-1 (OQ-01) for spec-draft; IM-2 (A-01) for Gate 1 if unconfirmed
- Artifact: `prd/reports/Impact-Map-INIT-STRATUM-HITL-WEB-001.md`

## Gate 1 — engineering handoff readiness

- [ ] Product/domain blocking questions are resolved in committed artifacts
- [ ] Impact-map scope and dependency order are complete
- [ ] PRD digest and map revision match this PR head
- [ ] PE/tech lead has reviewed the exact current head

Requested reviewer: @Sandvik-Common/stratum-pe-team
Initial label: `impact-map-pending`
```

## 12. Approval request (after Draft PR creation)

Tech lead must review this artifact on the meta PR and submit GitHub
**Approve** on the exact PR head SHA using:

```text
Impact map approved
initiative: INIT-STRATUM-HITL-WEB-001
map_revision: 1
meta_pr_head_sha: {SHA after this artifact is committed}
prd_digest: sha256:18ff1e8c74c4d9a7a056d27dd3974ca451695ddcbfc695f53bda8b46e6ce87c8
artifact: prd/reports/Impact-Map-INIT-STRATUM-HITL-WEB-001.md
```

The gate remains closed until the review, current PR head SHA, PRD digest, map
revision, and artifact path all match.

All Gate 1 labels must be provisioned before PR creation/update:

```bash
launchpad apply-gates --meta --apply
```

```yaml
handoff:
  contract: sdd-delivery/v2
  stage: prd-impact-map
  outcome: pass
  artifact:
    path: prd/reports/Impact-Map-INIT-STRATUM-HITL-WEB-001.md
    digest: sha256:345687ab2588a8d3ef49a9f9d1eb2e2f500db0949e87e836fe6309cd54eff3ff
  blockers: []
  signals:
    pr_ready: true
    map_revision: 1
    collision_detection: unrelated
    human_resolution: none
    affected_repos:
      - Sandvik-Common/stratum-hitl-web
    deferred_repos:
      - Sandvik-Common/stratum-platform-core
      - Sandvik-Common/stratum-iac-infra
      - Sandvik-Common/stratum-edge-agent
    source_prd_digest: sha256:18ff1e8c74c4d9a7a056d27dd3974ca451695ddcbfc695f53bda8b46e6ce87c8
    proposed_branch: chore/INIT-STRATUM-HITL-WEB-001-prd
    proposed_base: develop
  next_candidates:
    - prd-pr-action
  human_checkpoint: false
  external_action: true
  forge:
    action: open_draft_pr
    draft: true
    apply_labels:
      - impact-map-pending
    remove_labels: []
    title: "[INIT-STRATUM-HITL-WEB-001] PRD — Platform authoring UI (gate-first)"
    body_path: prd/reports/Impact-Map-INIT-STRATUM-HITL-WEB-001.md
```
