---
schema_version: 1
initiative: INIT-STRATUM-IAC-004
map_revision: 1
source_prd: prd/INIT-STRATUM-IAC-004.md
source_prd_digest: sha256:469d0d3dc184f49b88f6c0d0b5fc0fc447610c2b52ec1d5a1316dfc4c69e83d2
previous_revision: null
previous_artifact_commit: null
change_reason: initial map after Strict Schema PRD + validation pass (rev 2) for Azure infra-cohort slice (Kafka, CrateDB, EMQX, LiteLLM) under stratum-iac-infra
material_change: true
generated_at: 2026-09-01T10:10:03Z
---

# Impact map — INIT-STRATUM-IAC-004 — revision 1

> This file is generated locally before PR creation and becomes the scope source
> of truth when committed. Effective approval is derived from a tech-lead
> GitHub APPROVED review on the exact current meta PR head SHA; dynamic PR state
> is not stored in this artifact's frontmatter.

## 1. Source and revision

| Field | Value |
|-------|-------|
| PRD | `prd/INIT-STRATUM-IAC-004.md` |
| PRD digest | `sha256:469d0d3dc184f49b88f6c0d0b5fc0fc447610c2b52ec1d5a1316dfc4c69e83d2` |
| Map revision | `1` |
| Previous revision | none |
| Previous artifact commit | none |
| Change reason | Initial map for **infra cohort v1** (CAP-01 / REQ-01…12) after `/prd` from outline + validation pass 2 |
| Material change | yes — first map for this initiative |

### T0 identity (completed)

| Field | Value |
|-------|-------|
| Collision detection | `no-collision` |
| Human resolution | none |
| Evidence | No open PR for `INIT-STRATUM-IAC-004`. No `Impact-Map-INIT-STRATUM-IAC-004*`. Local branch `chore/INIT-STRATUM-IAC-004-prd` is this initiative’s working branch (not a competing PR). Sibling maps IAC-001 / IAC-002 are different INIT ids. Open meta PRs [#34](https://github.com/Sandvik-Common/stratum-meta/pull/34) (IAC-003), [#28](https://github.com/Sandvik-Common/stratum-meta/pull/28) (007-A), [#31](https://github.com/Sandvik-Common/stratum-meta/pull/31) (009) are other initiatives. Catalog file used: `config/service-catalog-Sandvik-Common.yaml` (no `config/service-catalog.yaml` in this clone). |
| External action authorized | false |

```yaml
identity_collision:
  detection: no-collision
  evidence:
    - no Impact-Map-INIT-STRATUM-IAC-004*
    - no open PR for INIT-STRATUM-IAC-004
    - local chore/INIT-STRATUM-IAC-004-prd is this INIT’s working branch
    - Impact-Map-INIT-STRATUM-IAC-001 / 002 are distinct INITs
    - open PR #34 is INIT-STRATUM-IAC-003; #28 is 007-A; #31 is 009
  recommended_resolution: null
  human_decision: none
  external_action_authorized: false
```

## 2. Affected repositories

| Service | Repo | Team | Scope summary | Scope digest | Spec to create | Confidence |
|---------|------|------|---------------|--------------|----------------|------------|
| stratum-iac-infra | Sandvik-Common/stratum-iac-infra | @Sandvik-Common/stratum-pe-team | Dev infra node pool on existing AKS plus ClusterIP Kafka (KRaft), CrateDB with telemetry DDL, EMQX, LiteLLM keys from Key Vault; written Helm/operator home; unblock IAC-005; no Autrio/Stratum deploys or HITL | `sha256:0f4af76f263b35e651f305c3b7b280e20624ee185f19b6c2c0abc0a6c9862c79` | `INIT-STRATUM-IAC-004-iac-infra.md` | High |

**Catalog match:** `stratum-iac-infra` owns Azure Terraform substrate — networking, **Kubernetes**, secrets, storage, observability. This initiative delivers the **infra-cohort slice** (REQ-01…12 / CAP-01) on the existing IAC-003 cluster (`sk-st-dev-aks`, ns `infra`). Helm/operators may live in a deploy repo once named (OQ-07 / REQ-12); until then the **written home** is still an iac-infra handover obligation, not a second catalog target.

## 3. Deferred repositories

| Service | Repo | Reason | Revisit condition |
|---------|------|--------|-------------------|
| — | — | No catalog service deferred as an engineering target for this wave beyond later programme inits | — |

**Deferred capabilities (later inits):** Autrio + Stratum app deploys + HITL edge (`IAC-005`); corporate DNS (`IAC-006`); stage replica counts / Crate 60 GB / infra ≥64 GB RAM (`IAC-007`); ClickHouse (`IAC-008+`).

## 4. Transitively affected repositories

| Service | Repo | Depends on | Potential impact | Disposition |
|---------|------|------------|------------------|-------------|
| — | — | — | Catalog has no `depends_on` edges; 004 smoke is in-cluster ClusterIP | not applicable |

## 5. Not affected

| Service | Repo | Reason |
|---------|------|--------|
| stratum-meta | Sandvik-Common/stratum-meta | Control-plane host for this PRD/map only — no `INIT-*-meta` eng spec |
| stratum-platform-core | Sandvik-Common/stratum-platform-core | Consumes ClusterIP brokers in **IAC-005**; no 004 app-feature or CI-publish DoD |
| stratum-hitl-web | Sandvik-Common/stratum-hitl-web | Public HITL edge is IAC-005; no 004 UX |
| stratum-edge-agent | Sandvik-Common/stratum-edge-agent | Device agent — no Kafka/Crate/EMQX/LiteLLM provisioning in this PRD |

**External (not in catalog):** Autrio / Docker Hub — Hub remains SoT (D2); Autrio MQTT/telemetry attach is IAC-005. Deploy/GitOps repo unnamed (programme O2 / PRD OQ-07) — REQ-12 requires a **written home**, not a named GitHub string as Gate 1. `stratum-iac-local` is protocol/DDL parity reference only.

## 6. Cross-repository contracts

| Contract ID | Provider repo | Consumer repo | Capability | Owner | Status |
|-------------|---------------|---------------|------------|-------|--------|
| — | — | — | Delivery is intra-`stratum-iac-infra` (infra pool + ClusterIP cohort) | — | n/a |

**Programme gate (not a catalog CTR):** written **IAC-005 unblock** (REQ-09) plus in-cluster DNS names (or naming pattern) for Kafka, Crate, EMQX, LiteLLM.

## 7. Dependency and build order

```text
Sandvik-Common/stratum-iac-infra
        (infra pool + Kafka + Crate+DDL + EMQX + LiteLLM — CAP-01 / REQ-01…12)
                │
                ▼ unblocks (next initiative, not this map)
        INIT-STRATUM-IAC-005 (Autrio + Stratum apps + HITL edge)
```

| Repo | Depends on | Reason |
|------|------------|--------|
| Sandvik-Common/stratum-iac-infra | IAC-001 (A1); IAC-002 (A2); IAC-003 cluster + ns `infra` (A3); BDC (A6) | Infra cohort on existing cluster; no VNet redesign (A4) |

**Engineering merge order:** open/implement eng spec **only** in **stratum-iac-infra** after Gate 1 `impact-map-lgtm`. Do not open platform-core / hitl-web / edge-agent specs for IAC-004.

## 8. Revision diff

Omit — map revision 1 (no prior Impact-Map artifact for this INIT).

## 9. Downstream ripple ledger

No prior map revision repositories for `INIT-STRATUM-IAC-004`. Seed ledger:

| Repo | In-flight artifact | Required action | Reason | Owner | Blocking |
|------|--------------------|-----------------|--------|-------|----------|
| Sandvik-Common/stratum-iac-infra | none | open | After Gate 1 `impact-map-lgtm` on matching meta PR head | stratum-pe-team | no (gate closed until LGTM) |

## 10. Open questions

| ID | Lane | Question | Owner | Blocking | Required by | Default if deferred | Status |
|----|------|----------|-------|----------|-------------|---------------------|--------|
| IM-1 | PE | Helm/operator/image versions (PRD OQ-01) | stratum-pe-team | no for Gate 1 | before live smoke | Local parity where practical; record in handover | open |
| IM-2 | PE | Infra-pool SKU name (PRD OQ-02) | stratum-pe-team | no for Gate 1 | before pool create | Floors bind; 003 suggested `Standard_D8s_v5` + 128 GB OS | open |
| IM-3 | PE | Kafka PVC size / StorageClass (PRD OQ-03) | stratum-pe-team | no for Gate 1 | before Kafka smoke | Dedicated PVC required; size PE | open |
| IM-4 | PE | Crate telemetry DDL file/commit (PRD OQ-04) | stratum-pe-team | no for Gate 1 | before REQ-03 | Must be applied and named in handover | open |
| IM-5 | PE | LiteLLM models + KV slot names (PRD OQ-05) | stratum-pe-team | no for Gate 1 | before REQ-05 | Values never in git | open |
| IM-6 | PE | Deploy/GitOps GitHub repo name (PRD OQ-07) and v1 chart home (OQ-09) | stratum-pe-team | no for Gate 1 | REQ-12 written home | Unnamed repo allowed; silence on home is not | open |

## 11. PR readiness handoff

| Item | Value |
|------|-------|
| Verdict | **PR READY** |
| Collision detection | `no-collision` |
| Collision evidence | No open IAC-004 PR; no prior IAC-004 map; #34 is IAC-003; #28/#31 unrelated |
| Human resolution | none |
| Resolution completed | n/a |
| Existing PR | none |
| Proposed branch | `chore/INIT-STRATUM-IAC-004-prd` |
| Proposed base | `develop` |
| Proposed title | `[INIT-STRATUM-IAC-004] PRD — Infra cohort v1 (Kafka, CrateDB, EMQX, LiteLLM)` |
| Files to commit | `prd/INIT-STRATUM-IAC-004.md`, `prd/INIT-STRATUM-IAC-004-outline.md`, `prd/reports/Impact-Map-INIT-STRATUM-IAC-004.md`, `prd/reports/Impact-Map-INIT-STRATUM-IAC-004-pr-body.md`, `prd/reports/Validation-Report-INIT-STRATUM-IAC-004.md`, `prd/reports/Resolution-INIT-STRATUM-IAC-004.md`, `prd/reports/Update-Summary-INIT-STRATUM-IAC-004.md` |
| Reviewer | @Sandvik-Common/stratum-pe-team |
| Initial Gate 1 label | `impact-map-pending` |
| Additional invalidation label | none |
| Blocking items | none for Draft PR / Gate 1 scope review |

**No GitHub side effects have occurred.** Ask whether to run **`/open-draft-pr`** (or authorize forge) to publish.

### Proposed Draft PR body

```markdown
## Product change

INIT-STRATUM-IAC-004 delivers Stratum’s **on-cluster infra cohort for dev** (programme `INIT-STRATUM-IAC`): an infra node pool on the existing Bangalore Design Center AKS, plus ClusterIP Kafka (KRaft), CrateDB with telemetry DDL, EMQX, and LiteLLM (keys from Key Vault) — and **unblocks** INIT-STRATUM-IAC-005 (apps + HITL edge). It does **not** ship Autrio/Stratum application deploys, a public HITL URL, public MQTT, or stage replica counts.

## Impact-map summary
- Revision: 1
- PRD digest: `sha256:469d0d3dc184f49b88f6c0d0b5fc0fc447610c2b52ec1d5a1316dfc4c69e83d2`
- Affected repos: Sandvik-Common/stratum-iac-infra
- Deferred repos: none (later IAC-005…007 / 008+ are separate inits)
- Blocking questions: none for Gate 1
- Artifact: `prd/reports/Impact-Map-INIT-STRATUM-IAC-004.md`

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
initiative: INIT-STRATUM-IAC-004
map_revision: 1
meta_pr_head_sha: {SHA after this artifact is committed}
prd_digest: sha256:469d0d3dc184f49b88f6c0d0b5fc0fc447610c2b52ec1d5a1316dfc4c69e83d2
artifact: prd/reports/Impact-Map-INIT-STRATUM-IAC-004.md
```

The gate remains closed until the review, current PR head SHA, PRD digest, map
revision, and artifact path all match.

```yaml
handoff:
  contract: sdd-delivery/v2
  stage: prd-impact-map
  outcome: pass
  artifact:
    path: prd/reports/Impact-Map-INIT-STRATUM-IAC-004.md
  blockers: []
  signals:
    initiative: INIT-STRATUM-IAC-004
    map_revision: 1
    source_prd: prd/INIT-STRATUM-IAC-004.md
    source_prd_digest: sha256:469d0d3dc184f49b88f6c0d0b5fc0fc447610c2b52ec1d5a1316dfc4c69e83d2
    affected_repos:
      - Sandvik-Common/stratum-iac-infra
    pr_ready: true
    collision_detection: no-collision
  next_candidates:
    - prd-pr-action
  human_checkpoint: false
  external_action: true
  forge:
    action: open_draft_pr
    draft: true
    title: "[INIT-STRATUM-IAC-004] PRD — Infra cohort v1 (Kafka, CrateDB, EMQX, LiteLLM)"
    body_path: prd/reports/Impact-Map-INIT-STRATUM-IAC-004-pr-body.md
    apply_labels:
      - impact-map-pending
    base: develop
    head: chore/INIT-STRATUM-IAC-004-prd
    reviewers:
      - Sandvik-Common/stratum-pe-team
    commit_workspace: required
```
