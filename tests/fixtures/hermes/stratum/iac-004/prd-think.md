# INIT-STRATUM-IAC-004 — Infra cohort v1 (Kafka, CrateDB, EMQX, LiteLLM)

*Product-authored | Strict Schema from outline | Fourth delivery slice under programme `INIT-STRATUM-IAC` | Owned substrate: `stratum-iac-infra` | DRAFT | September 2026*

**Source outline:** [`prd/INIT-STRATUM-IAC-004-outline.md`](INIT-STRATUM-IAC-004-outline.md)  
**Programme baseline:** [`planning/STRATUM-IAC.md`](../planning/STRATUM-IAC.md) §5.5, §8.4–§8.5, D5–D6, D9, D11–D12, D17–D19  
**Covers programme phase:** 5 (infra cohort v1 on AKS)  
**Prior init:** `INIT-STRATUM-IAC-003` (AKS + Postgres + Redis — PE **unblocked — IAC-004 may start** 2026-09-01, iac-infra PR #52). Formal 003 PRD is **not** in this tree yet (`chore/INIT-STRATUM-IAC-003-prd`); until it lands on `develop`, prior-init SSOT is programme [`planning/STRATUM-IAC.md`](../planning/STRATUM-IAC.md) **§5.4** + IAC-003 as-built.  
**Impact repo (primary):** `Sandvik-Common/stratum-iac-infra`  
**Impact repo (charts, if named):** deploy/GitOps repo — **name still programme O2 / OQ-07**; 004 still requires a **written home** for Helm/operators (D9).

**Discovery method:** no new interview. Locks below are taken from the outline, programme baseline, IAC-003 as-built (cluster `sk-st-dev-aks`, ns `infra`, infra-pool path), and sibling IAC-001/002 PRDs (003 PRD not on this tree). Items in outline §6 stay PE-owned `OQ-*`, not invented DoD.

**Discovery locks (this draft):**

| Lock | Value | Source |
|------|-------|--------|
| Why now | Cluster + managed data exist; brokers must land **before** Autrio telemetry/MQTT paths are expected to be real | Outline §1; programme §5.5 |
| Scope | Kafka + CrateDB + EMQX + LiteLLM on **dev** AKS — **not** merged with IAC-005/006/007/008 | Outline §2–§3 `(Source: outline)` |
| Placement | On-cluster infra cohort (D5); **not** Azure PaaS substitutes in v1 | Programme D5 |
| Network | **ClusterIP only**; backends not on the internet (D6/D11); MQTT not on HITL Front Door | Outline §2; programme D6, D11, O4 |
| Dev topology | Kafka KRaft **1** broker + dedicated PVC; Crate **1** / **30 GB**; EMQX **1**; LiteLLM 1 small | Outline §2; programme D17–D18, §8.5 |
| Infra pool | **Create** on existing cluster / existing node subnet; **≥32 GB RAM / ~100 GB OS**; typically 1 node on **dev** | Outline §2; programme D19; 003 W3 path |
| Cloud home | Same as 001–003: BDC (`d4330423-f24e-4dfa-a8ba-d84d16bbc638`); RG **`rg-01-BDC-Stratum`**; region **southindia** | Outline §4; programme D13 |
| Consume, do not replace | Cluster `sk-st-dev-aks`; ns `infra`; VNet/subnets; ACR; KV; PG; Redis | Outline §3–§4; 003 as-built |
| Stage sizes | **Not** part of 004 DoD | Outline §3; programme D14 / IAC-007 |
| Product UX | **None** | Outline §3 |
| Chart versions / SKU names / models | PE-owned; not DoD strings | Outline §6 |
| Acceptance owner | **`stratum-pe-team`** (team-level sign-off sufficient) | Inherit 001–003 |
| Unblock next init | **IAC-004 must