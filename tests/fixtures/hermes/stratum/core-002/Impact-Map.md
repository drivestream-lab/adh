---
schema_version: 1
initiative: INIT-STRATUM-PLATFORM-CORE-002
map_revision: 1
source_prd: prd/INIT-STRATUM-PLATFORM-CORE-002.md
source_prd_digest: sha256:a8c145f43fd366fe2d2dc0b3f78df094b5488a7c216fe65d33c266cc37e795de
previous_revision: null
previous_artifact_commit: null
change_reason: initial map — Situation → model run → Promotion → Foundation entry after validate pass
material_change: true
generated_at: 2026-09-16T09:04:26Z
---

# Impact map — INIT-STRATUM-PLATFORM-CORE-002 — revision 1

> This file is generated locally before PR creation and becomes the scope source
> of truth when committed. Effective approval is derived from a tech-lead
> GitHub APPROVED review on the exact current meta PR head SHA; dynamic PR state
> is not stored in this artifact's frontmatter.

## 1. Source and revision

| Field | Value |
|-------|-------|
| PRD | `prd/INIT-STRATUM-PLATFORM-CORE-002.md` |
| PRD digest | `sha256:a8c145f43fd366fe2d2dc0b3f78df094b5488a7c216fe65d33c266cc37e795de` |
| Map revision | `1` |
| Previous revision | none |
| Previous artifact commit | none |
| Change reason | Initial map after validate pass (report_revision 3) |
| Material change | **yes** — first map |

### T0 identity (completed)

| Field | Value |
|-------|-------|
| Collision detection | `no-collision` |
| Human resolution | none |
| Evidence | Local branch `chore/INIT-STRATUM-PLATFORM-CORE-002-prd`; no prior Impact-Map for 002; no open meta PR for CORE-002 (open #50 is IAC-008 unrelated) |
| External action authorized | false (content skill only) |

```yaml
identity_collision:
  detection: no-collision
  evidence:
    - branch chore/INIT-STRATUM-PLATFORM-CORE-002-prd (this INIT)
    - no Impact-Map-INIT-STRATUM-PLATFORM-CORE-002.md prior
    - open meta PRs: #50 IAC-008 only (unrelated)
  recommended_resolution: null
  human_decision: none
  external_action_authorized: false
```

### Capability areas (T1)

| Area | PRD refs | Notes |
|------|----------|-------|
| Situation authoring ⊆ pin | CAP-01–02, REQ-01–04, J-01–J-03 | Page 05 |
| Model run + claims | CAP-03, REQ-05–08, J-04–J-06 | SceneIQ cast |
| Promotion Suggest→Endorse→Approve | CAP-04, REQ-09–12, REQ-23, J-07–J-09 | Supersedes 001 shell |
| Foundation entry (done) | CAP-05, REQ-13–15, REQ-24–25, J-10–J-11, J-16 | Uses CORE-001 tools |
| Model-run publish | CAP-06, REQ-16, J-12 | Live store only |
| Pin-safe concurrency + retarget consume | CAP-07–08, REQ-17–19, J-13–J-14 | Retarget write = CORE-001 |
| ViewModels + authz | CAP-09, REQ-20–21 | Shape for FE |
| U09 stub | CAP-10, REQ-22, J-15 | Not Conformance |

**Catalog:** `config/service-catalog-Sandvik-Common.yaml` (single match).

## 2. Affected repositories

| Service | Repo | Team | Scope summary | Scope digest | Spec to create | Confidence |
|---------|------|------|---------------|--------------|----------------|------------|
| stratum-platform-core | Sandvik-Common/stratum-platform-core | @Sandvik-Common/stratum-platform-devs | Situation Model-run Promotion workflow Foundation-entry ViewModels authz pin-safe concurrency; consume CORE-001 pin retarget and Foundation publish; API ViewModels only; U09 stub; no hitl-web pages 05-06 | `sha256:a9d2fdb0bf0226ebef930b317246ffd5e7016fd9727b8dc93babce2ce36830e7` | `INIT-STRATUM-PLATFORM-CORE-002-platform-core.md` | High |

**H2 payload:**

```text
repo=Sandvik-Common/stratum-platform-core
status=affected
capabilities=CAP-01,CAP-02,CAP-03,CAP-04,CAP-05,CAP-06,CAP-07,CAP-08,CAP-09,CAP-10,REQ-01,REQ-02,REQ-03,REQ-04,REQ-05,REQ-06,REQ-07,REQ-08,REQ-09,REQ-10,REQ-11,REQ-12,REQ-13,REQ-14,REQ-15,REQ-16,REQ-17,REQ-18,REQ-19,REQ-20,REQ-21,REQ-22,REQ-23,REQ-24,REQ-25
contracts=CTR-01,CTR-02,CTR-03,CTR-04,CTR-05,CTR-06
depends_on=
scope=Situation Model-run Promotion workflow Foundation-entry ViewModels authz pin-safe concurrency; consume CORE-001 pin retarget and Foundation publish; API ViewModels only; U09 stub; no hitl-web pages 05-06
```

**Catalog match:** description explicitly owns situations, model runs, and promotions — primary delivery home.

## 3. Deferred repositories

| Service | Repo | Reason | Revisit condition |
|---------|------|--------|-------------------|
| stratum-hitl-web | Sandvik-Common/stratum-hitl-web | PRD non-goal / `OQ-05`: no pages 05–06 UI in this INIT; CTR-01…03 consumers only | Parallel FE INIT or OQ-05 closed to ship UI |

## 4. Transitively affected repositories

Catalog has **no** `depends_on` edges.

| Service | Repo | Depends on | Potential impact | Disposition |
|---------|------|------------|------------------|-------------|
| stratum-hitl-web | Sandvik-Common/stratum-hitl-web | platform-core ViewModels (logical) | Will consume CTR-01…03 when FE ships | deferred / monitor |

## 5. Not affected

| Service | Repo | Reason |
|---------|------|--------|
| stratum-meta | Sandvik-Common/stratum-meta | Control-plane host for PRD/map only |
| stratum-edge-agent | Sandvik-Common/stratum-edge-agent | No Situation/Model-run/Promotion authoring; SceneIQ scrape is out of programme |
| stratum-iac-infra | Sandvik-Common/stratum-iac-infra | No new substrate capability in this PRD |

**External / future:** CORE-003 consumes CTR-06 model-run ids (not a catalog repo yet as separate service).

## 6. Cross-repository contracts

| Contract ID | Provider repo | Consumer repo | Capability | Owner | Status |
|-------------|---------------|---------------|------------|-------|--------|
| CTR-01 | Sandvik-Common/stratum-platform-core | downstream UI (hitl-web deferred) | Situation create/update/read | platform-devs | **new** |
| CTR-02 | Sandvik-Common/stratum-platform-core | downstream UI (deferred) | Model run create/claims/read | platform-devs | **new** |
| CTR-03 | Sandvik-Common/stratum-platform-core | downstream UI (deferred) | Promotion Suggest/Endorse/Approve | platform-devs | **new** |
| CTR-04 | Sandvik-Common/stratum-platform-core | CORE-001 Foundation tools (same repo) | Approved → catalog draft / RC handoff | platform-devs | **new** (intra-service) |
| CTR-05 | Sandvik-Common/stratum-platform-core | CORE-001 pin API (same repo) | Observe pin; invoke retarget | platform-devs | **new** (consume) |
| CTR-06 | Sandvik-Common/stratum-platform-core | CORE-003 (future) | Model-run id + pin binding handoff | platform-devs | **new** |

## 7. Dependency and build order

```text
Sandvik-Common/stratum-platform-core
   (CORE-001 pin + publish + retarget already live)
        → CAP-01…10 / REQ-01…25 (this INIT)
             ├─ CTR-01…03 → hitl-web (deferred)
             └─ CTR-06 → CORE-003 (later)
```

| Repo | Depends on | Reason |
|------|------------|--------|
| Sandvik-Common/stratum-platform-core | CORE-001 surfaces in same repo | A-01 confirmed; Foundation entry + retarget consume |
| Sandvik-Common/stratum-hitl-web | platform-core | Deferred until OQ-05 |

**Engineering merge order:** After Gate 1 `impact-map-lgtm`, open **platform-core** product spec only. Do not open hitl-web eng spec under this INIT.

## 8. Revision diff

Omit — revision 1.

## 9. Downstream ripple ledger

| Repo | In-flight artifact | Required action | Reason | Owner | Blocking |
|------|--------------------|-----------------|--------|-------|----------|
| Sandvik-Common/stratum-platform-core | none | open | First map; open after Gate 1 LGTM | stratum-platform-devs | no (gate closed until LGTM) |
| Sandvik-Common/stratum-hitl-web | none | hold | Deferred FE | stratum-frontend-devs | no |

## 10. Open questions

| ID | Lane | Question | Owner | Blocking | Required by | Default if deferred | Status |
|----|------|----------|-------|----------|-------------|---------------------|--------|
| IM-1 | PM + PE | OQ-01: Exact Promotion field set for Foundation entry | PM + PE | soft | spec-draft | Gap description + target vocabulary key + source model-run ref | open |
| IM-2 | PE | OQ-07: Draft identity immediately vs assist into CORE-001 create-draft | PE | soft | spec-draft | Linked draft identity (REQ-13) | open |
| IM-3 | PM | OQ-05: Parallel hitl-web INIT for pages 05–06? | PM | no | impact-map / later | API + ViewModels only in CORE-002 | open |
| IM-4 | PM | OQ-06: Who may invoke CORE-001 retarget | PM | no | spec-draft | Architect retargets; owner Approves only | open |

> **Gate 1:** No hard blockers. Soft IM-1/IM-2 use PRD defaults for spec-draft. Draft meta PR may proceed.

## 11. PR readiness handoff

| Item | Value |
|------|-------|
| Verdict | **PR READY** |
| Collision detection | no-collision |
| Collision evidence | Branch for this INIT; no prior 002 map; open #50 unrelated |
| Human resolution | none |
| Resolution completed | n/a |
| Existing PR | none |
| Proposed branch | `chore/INIT-STRATUM-PLATFORM-CORE-002-prd` |
| Proposed base | `develop` |
| Proposed title | `[INIT-STRATUM-PLATFORM-CORE-002] PRD — Situation → model run → Promotion → Foundation entry` |
| Files to commit | `prd/INIT-STRATUM-PLATFORM-CORE-002.md`, this impact map, `prd/reports/Validation-Report-INIT-STRATUM-PLATFORM-CORE-002.md`, `prd/reports/Resolution-INIT-STRATUM-PLATFORM-CORE-002.md`, `prd/reports/Update-Summary-INIT-STRATUM-PLATFORM-CORE-002.md`, think/quality reports |
| Reviewer | @Sandvik-Common/stratum-pe-team |
| Initial Gate 1 label | `impact-map-pending` |
| Additional invalidation label | none |
| Blocking items | none for Draft PR |

**No GitHub side effects have occurred.** Ask the user whether to create the Draft PR (`/commit-workspace` then `/open-draft-pr`). Continue only after explicit authorization.

### Proposed Draft PR body

```markdown
## Product change

Platform-core delivers **Situation** authoring (values ⊆ pin), **Model run** in-scope / out-of-scope claims, **Promotion** Suggest → Endorse → Approve, and **Foundation entry** of approved gaps via CORE-001 machinery — pin-safe (accept ≠ retarget). Africa + Finland/Kevitsa casts. API + ViewModels only; pages 05–06 UI deferred (`OQ-05`).

## Impact-map summary

- Revision: 1
- PRD digest: `sha256:a8c145f43fd366fe2d2dc0b3f78df094b5488a7c216fe65d33c266cc37e795de`
- Affected repos: Sandvik-Common/stratum-platform-core
- Deferred repos: stratum-hitl-web (`OQ-05`)
- Blocking questions: none for Gate 1 Draft (IM-1/IM-2 soft with defaults)
- Artifact: `prd/reports/Impact-Map-INIT-STRATUM-PLATFORM-CORE-002.md`

## Gate 1 — engineering handoff readiness

- [ ] Product/domain blocking questions are resolved or defaulted in committed artifacts
- [ ] Impact-map scope and dependency order are complete
- [ ] PRD digest and map revision match this PR head
- [ ] PE/tech lead has reviewed the exact current head

Requested reviewer: @Sandvik-Common/stratum-pe-team
Initial label: `impact-map-pending`
```

## 12. Approval request (after Draft PR creation)

```text
Impact map approved
initiative: INIT-STRATUM-PLATFORM-CORE-002
map_revision: 1
meta_pr_head_sha: {SHA after this artifact is committed}
prd_digest: sha256:a8c145f43fd366fe2d2dc0b3f78df094b5488a7c216fe65d33c266cc37e795de
artifact: prd/reports/Impact-Map-INIT-STRATUM-PLATFORM-CORE-002.md
```

```yaml
handoff:
  contract: sdd-delivery/v2
  stage: prd-impact-map
  outcome: pass
  artifact:
    path: prd/reports/Impact-Map-INIT-STRATUM-PLATFORM-CORE-002.md
  blockers: []
  signals:
    map_revision: 1
    source_prd_digest: sha256:a8c145f43fd366fe2d2dc0b3f78df094b5488a7c216fe65d33c266cc37e795de
    scope_digest_platform_core: sha256:a9d2fdb0bf0226ebef930b317246ffd5e7016fd9727b8dc93babce2ce36830e7
    pr_ready: true
    collision_detection: no-collision
    affected_repos:
      - Sandvik-Common/stratum-platform-core
    deferred_repos:
      - Sandvik-Common/stratum-hitl-web
  next_candidates:
    - prd-pr-action
  human_checkpoint: false
  external_action: true
  forge:
    action: open_draft_pr
    draft: true
    title: "[INIT-STRATUM-PLATFORM-CORE-002] PRD — Situation → model run → Promotion → Foundation entry"
    base: develop
    head: chore/INIT-STRATUM-PLATFORM-CORE-002-prd
    apply_labels:
      - impact-map-pending
    reviewers:
      - Sandvik-Common/stratum-pe-team
```
