---
schema_version: 1
initiative: INIT-STRATUM-008
map_revision: 1
source_prd: prd/INIT-STRATUM-008.md
source_prd_digest: sha256:a34ee13b0496ad16dc0fe56cb61b1bd44b4eee484963484748a14cd2c706ee8a
previous_revision: null
previous_artifact_commit: null
change_reason: initial map after Strict Schema PRD + Resolution CHG-01–CHG-09 + incremental validate pass (report_revision 3, 0 open VF-*)
material_change: true
generated_at: 2026-08-19T09:24:00Z
---

# Impact map — INIT-STRATUM-008 — revision 1

> This file is generated locally before PR creation and becomes the scope source
> of truth when committed. Effective approval is derived from a tech-lead
> GitHub APPROVED review on the exact current meta PR head SHA; dynamic PR state
> is not stored in this artifact's frontmatter.

## 1. Source and revision

| Field | Value |
|-------|-------|
| PRD | `prd/INIT-STRATUM-008.md` |
| PRD digest | `sha256:a34ee13b0496ad16dc0fe56cb61b1bd44b4eee484963484748a14cd2c706ee8a` |
| Map revision | `1` |
| Previous revision | none |
| Previous artifact commit | none |
| Change reason | Initial map for Edge Agent Autrio join (identity, Setu bootstrap, control/data path addressing). Validation `report_revision` 3 — 0 open findings. |
| Material change | yes — first map for this initiative |

### T0 identity (completed)

| Field | Value |
|-------|-------|
| Collision detection | `no-collision` |
| Human resolution | none (user confirmed continue) |
| Evidence | No `Impact-Map-INIT-STRATUM-008*`. No GitHub PRs matching INIT-STRATUM-008 (open or closed search). Local branch `develop`; 008 PRD/report files untracked only. Open drafts [#27](https://github.com/Sandvik-Common/stratum-meta/pull/27) (`INIT-STRATUM-007-A`) and [#28](https://github.com/Sandvik-Common/stratum-meta/pull/28) (`INIT-STRATUM-IAC-001`) are **unrelated**. `INIT-STRATUM-006` is a distinct runtime initiative (008 supersedes connectivity/path addressing only). |
| External action authorized | false |

```yaml
identity_collision:
  detection: no-collision
  evidence:
    - no Impact-Map-INIT-STRATUM-008
    - no GitHub PRs for INIT-STRATUM-008
    - open #27 INIT-STRATUM-007-A (unrelated)
    - open #28 INIT-STRATUM-IAC-001 (unrelated)
    - INIT-STRATUM-006 is a sibling runtime init, not the same business PRD
  recommended_resolution: null
  human_decision: none
  external_action_authorized: false
```

### Capability areas (T1)

| Area | PRD refs | Notes |
|------|----------|-------|
| Serial identity | CAP-01, REQ-01, REQ-02, US-1–US-2 | Settings serial is join name; optional machine read warn once per start |
| Autrio Setu join | CAP-02, REQ-03, SC7, A2, OQ-01 | Serial + secret + Setu URL; no tenant id on device (at-risk until A2) |
| Secret persist | CAP-05, REQ-06, US-6 | Env first run; then secure store; persist whatever Autrio returns |
| Control path addressing | CAP-03, REQ-04, US-4, A3, OQ-02 | Listen update + command; missing names fail Phase 1 |
| Data path addressing | CAP-04, REQ-05, US-5 | 006 scrape/store; Autrio send names; required sends fail Phase 1 |
| Message-path session | US-3, US-7, REQ-07, A5 | Session token; TLS or plain as Autrio returns; no mTLS |
| Liveness | REQ-09, OQ-06 | Broker keep-alive this init; 006 Instance Record patched later |
| Failure distinguish | REQ-08, §4.4 | Join fail vs connect fail |
| 006 supersession | CAP-06, REQ-07, §4.7 | Connectivity and path addressing only; not scrape/OTA execution |

## 2. Affected repositories

| Service | Repo | Team | Scope summary | Scope digest | Spec to create | Confidence |
|---------|------|------|---------------|--------------|----------------|------------|
| stratum-edge-agent | Sandvik-Common/stratum-edge-agent | @Sandvik-Common/stratum-platform-devs | Phase 1 Autrio Setu join on-device: serial in settings as join name (CAP-01, REQ-01); optional machine-serial warn at most once per start (REQ-02); serial+env-secret+Setu URL join with persist-returned-secret (CAP-02, REQ-03, REQ-06); no tenant id on device (SC7 at-risk A2/OQ-01); session token; TLS or plain as Autrio returns; no mTLS; required Autrio listen names update+command (CAP-03, REQ-04); 006 scrape/store then Autrio send map with required send names fail-closed (CAP-04, REQ-05); broker keep-alive liveness (REQ-09); Setu join is Phase 1 done not pre-baked path (CAP-06, REQ-07); ops-distinguishable join vs connect fail (REQ-08) | `sha256:9158ea0df91fff758de1789c32cc3f5fe4a4c8eb3fb66c6493d0838c80a63301` | `INIT-STRATUM-008-edge-agent.md` | High |

**H2 payload (canonical UTF-8/LF JSON, `sort_keys`, one trailing newline):** `capabilities` CAP-01–CAP-06; `requirements` REQ-01–REQ-09; `contracts` CTR-01–CTR-03; `depends_on` empty; `initiative` INIT-STRATUM-008; `repo` Sandvik-Common/stratum-edge-agent; `scope` = table scope summary (single line).

**Catalog match:** `stratum-edge-agent` owns device-side OTA reconciliation, buffers, and telemetry forward — the only live catalog service that implements on-device Autrio join, destination binding, and secret store. Autrio Setu/broker are **external** (not catalog). `stratum-platform-core` owns ODD/model registry/HITL policy, not Setu join or MQTT path addressing.

## 3. Deferred repositories

| Service | Repo | Reason | Revisit condition |
|---------|------|--------|-------------------|
| stratum-iac-infra | Sandvik-Common/stratum-iac-infra | PRD non-goals Azure/factory image homes (`INIT-STRATUM-INFRA-001`). Phase 1 Setu URL is device settings; no new IaC product capability. | Production network/secrets for Autrio Setu or broker if substrate-owned (not device settings) |
| stratum-platform-core | Sandvik-Common/stratum-platform-core | 008 does not add cloud APIs. 006 Instance Record / heartbeat amendment is **OQ-06** (do not edit 006 in this init). Cloud “online” for 008 is broker keep-alive. | When OQ-06 / a 006 follow-up specifies which cloud records change |

## 4. Transitively affected repositories

Catalog YAML has **no** `depends_on` edges. Scaffold/PRD notes:

| Service | Repo | Depends on | Potential impact | Disposition |
|---------|------|------------|------------------|-------------|
| stratum-hitl-web | Sandvik-Common/stratum-hitl-web | stratum-platform-core (BFF upstream) | No join UI in 008; future visibility of “online” may follow OQ-06 | not affected (monitor later via 006/OQ-06) |
| stratum-platform-core | Sandvik-Common/stratum-platform-core | Autrio (identity elsewhere) | Consumers of 006 presence JSON may need a later amendment | deferred (OQ-06) |
| stratum-iac-infra | Sandvik-Common/stratum-iac-infra | runtime substrate | Possible later Autrio endpoint wiring | deferred |

## 5. Not affected

| Service | Repo | Reason |
|---------|------|--------|
| stratum-hitl-web | Sandvik-Common/stratum-hitl-web | Catalog: reviewer console for OTA/policy/audit. 008 has no reviewer-facing join or approval stories. |
| stratum-meta | Sandvik-Common/stratum-meta | Control-plane host for this PRD/map PR only — not an app implementation target (no `INIT-*-meta` eng spec). |

**External (not in catalog):**

| Party | Role | Track via |
|-------|------|-----------|
| Autrio Setu + registry/secret service | Join API; serial+secret; session, connectivity, listen/send maps | CTR-01, CTR-03; OQ-01, OQ-02 |
| Autrio message broker | Session-authenticated path; TLS or plain as join returns; keep-alive | CTR-02; REQ-09 |
| INIT-STRATUM-006 runtime | Unchanged scrape / store / update-execution; connectivity superseded | CAP-06; OQ-06 |
| INIT-STRATUM-002 / 003 | Still own *what* to deploy and metric *meaning* | PRD §4.7 |

## 6. Cross-repository contracts

| Contract ID | Provider repo | Consumer repo | Capability | Owner | Status |
|-------------|---------------|---------------|------------|-------|--------|
| CTR-01 | Autrio Setu (external) | Sandvik-Common/stratum-edge-agent | Join by serial + secret; persist returned secret; no tenant id from agent (at-risk A2) — CAP-02, REQ-03, REQ-06 | Autrio + edge | new |
| CTR-02 | Autrio broker (external) | Sandvik-Common/stratum-edge-agent | Connect with session token; TLS or plain as Autrio returns; no mTLS; keep-alive liveness — REQ-07, REQ-09 | Autrio + edge | new |
| CTR-03 | Autrio Setu (external) | Sandvik-Common/stratum-edge-agent | Named listen map (update + command required) and send map (required sends fail-closed); exact strings OQ-02 — REQ-04, REQ-05 | Autrio + Product + edge | new |

No **new** catalog-to-catalog contract this init (platform-core is not a 008 provider or consumer until OQ-06).

## 7. Dependency and build order

```text
Autrio Setu (join) + Autrio broker (session / keep-alive)
        ↓
Sandvik-Common/stratum-edge-agent
        ↘ (later, OQ-06) Sandvik-Common/stratum-platform-core  — 006 presence amendment
        ↘ (later) Sandvik-Common/stratum-iac-infra             — env only if needed
```

| Repo | Depends on | Reason |
|------|------------|--------|
| Sandvik-Common/stratum-edge-agent | Autrio Setu + broker; 006 scrape/store already in same repo | Slave to Autrio join maps; does not invent destinations |
| Sandvik-Common/stratum-platform-core | — | Deferred OQ-06 |
| Sandvik-Common/stratum-iac-infra | — | Deferred env |

**Engineering merge order (Phase 1):** open **edge-agent** spec PR only (`docs/specification/product/INIT-STRATUM-008.md` / `INIT-STRATUM-008-edge-agent.md` per eng layout). Do not open platform-core, hitl-web, or iac-infra eng specs for this initiative until revisit conditions fire.

## 8. Revision diff

Omit — map revision 1 (no prior Impact-Map artifact).

## 9. Downstream ripple ledger

No prior map revision repositories. Seed ledger for this revision:

| Repo | In-flight artifact | Required action | Reason | Owner | Blocking |
|------|--------------------|-----------------|--------|-------|----------|
| Sandvik-Common/stratum-edge-agent | none | open | After Gate 1 `impact-map-lgtm` on matching meta PR head | stratum-platform-devs / PE | no (gate closed until LGTM) |
| Sandvik-Common/stratum-platform-core | none | hold | Deferred OQ-06 | stratum-platform-devs | no |
| Sandvik-Common/stratum-hitl-web | none | hold | Not affected Phase 1 | stratum-frontend-devs | no |
| Sandvik-Common/stratum-iac-infra | none | hold | Deferred Phase 1 | stratum-pe-team | no |

## 10. Open questions

| ID | Lane | Question | Owner | Blocking | Required by | Default if deferred | Status |
|----|------|----------|-------|----------|-------------|---------------------|--------|
| IM-1 | domain | OQ-01: Confirm Autrio Setu join by serial with **no** tenant id | Autrio + Product | no for Draft PR; **yes** to close SC7 | before treating serial-only as Autrio-closed | Agent settings stay serial-only; join may fail until Autrio matches (PRD) | open |
| IM-2 | domain | OQ-02: Exact Autrio names for update, command, and required metric sends | Autrio + Product | no for Draft PR; **yes** to claim SC4/SC5 done | before Phase 1 control/data-path done | Spec binds roles dynamically; fail-closed if required names missing | open |
| IM-3 | PM / PE | OQ-06: Which 006 Instance Record / heartbeat fields to amend after 008 is accepted | Product | no | after Gate 1; before claiming 006 docs match 008 liveness | 008 remains join SoT; do not patch 006 in this init | open |
| IM-4 | PE | Catalog teams are platform/backend-devs; org may have `stratum-edge-devs` — CODEOWNERS for edge spec? | PE + Platform | no | after LGTM | Default: catalog teams for Gate 1 | open |

## 11. PR readiness handoff

| Item | Value |
|------|-------|
| Verdict | **PR READY** |
| Collision detection | no-collision |
| Collision evidence | No Impact-Map-008; no 008 GitHub PRs; open #27/#28 unrelated; 006 is sibling not duplicate |
| Human resolution | none |
| Resolution completed | n/a |
| Existing PR | none |
| Proposed branch | `chore/INIT-STRATUM-008-prd` |
| Proposed base | `develop` |
| Proposed title | `[INIT-STRATUM-008] PRD — Edge Agent Autrio Join` |
| Files to commit | `prd/INIT-STRATUM-008.md`, `prd/INIT-STRATUM-008-outline.md`, `prd/reports/Validation-Report-INIT-STRATUM-008.md`, `prd/reports/Resolution-INIT-STRATUM-008.md`, `prd/reports/Update-Summary-INIT-STRATUM-008.md`, `prd/reports/Impact-Map-INIT-STRATUM-008.md`, `prd/reports/Draft-PR-Body-INIT-STRATUM-008.md` |
| Reviewer | @Sandvik-Common/stratum-pe-team |
| Initial Gate 1 label | `impact-map-pending` |
| Additional invalidation label | none |
| Blocking items | none for Draft PR; IM-1/IM-2 block Autrio-closed SC7/SC4/SC5 only |

**No GitHub side effects have occurred.** Ask the user whether to create the Draft PR (`/open-draft-pr`). Continue only after explicit authorization.

### Proposed Draft PR body

See `prd/reports/Draft-PR-Body-INIT-STRATUM-008.md`.

## 12. Approval request (after Draft PR creation)

Tech lead must review this artifact on the meta PR and submit GitHub
**Approve** on the exact PR head SHA using:

```text
Impact map approved
initiative: INIT-STRATUM-008
map_revision: 1
meta_pr_head_sha: {SHA after this artifact is committed}
prd_digest: sha256:a34ee13b0496ad16dc0fe56cb61b1bd44b4eee484963484748a14cd2c706ee8a
artifact: prd/reports/Impact-Map-INIT-STRATUM-008.md
```

The gate remains closed until the review, current PR head SHA, PRD digest, map
revision, and artifact path all match.

All Gate 1 labels must be provisioned before PR creation/update:

```bash
launchpad apply-gates --meta --apply
```

Apply labels through the GitHub REST issues-label endpoint and request team
review through the REST `requested_reviewers` endpoint. Do not use `gh pr edit`
for these operations because its GraphQL path may fail on deprecated Projects
Classic fields.

PE updates labels as follows:

| Decision | Remove | Add |
|----------|--------|-----|
| Pending/new revision | `impact-map-lgtm`, `impact-map-blocked` | `impact-map-pending` |
| Request changes/hold | `impact-map-pending`, `impact-map-lgtm` | `impact-map-blocked` |
| Approve current head | `impact-map-pending`, `impact-map-blocked`, `impact-map-revised`, `impact-map-stale` | `impact-map-lgtm` |

```yaml
handoff:
  contract: sdd-delivery/v2
  stage: prd-impact-map
  outcome: pass
  artifact:
    path: prd/reports/Impact-Map-INIT-STRATUM-008.md
    digest: sha256:cf239800f63969a8b600a0f4814de0f64d3738ac89642a0fe701c7be04b599dd
  blockers: []
  signals:
    pr_ready: true
    map_revision: 1
    collision_detection: no-collision
    human_resolution: none
    affected_repos:
      - Sandvik-Common/stratum-edge-agent
    deferred_repos:
      - Sandvik-Common/stratum-platform-core
      - Sandvik-Common/stratum-iac-infra
    source_prd_digest: sha256:a34ee13b0496ad16dc0fe56cb61b1bd44b4eee484963484748a14cd2c706ee8a
    proposed_branch: chore/INIT-STRATUM-008-prd
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
    title: "[INIT-STRATUM-008] PRD — Edge Agent Autrio Join"
    body_path: prd/reports/Draft-PR-Body-INIT-STRATUM-008.md
```
