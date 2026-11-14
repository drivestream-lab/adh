# INIT-STRATUM-PLATFORM-CORE-002: Situation → model run → Promotion (prd-think candidate)

| Field | Value |
|-------|-------|
| Initiative | INIT-STRATUM-PLATFORM-CORE-002 |
| Status | candidate (run 1) |
| Brief | Conversation (Sep 2026); `prd/INIT-STRATUM-PLATFORM-CORE-002-outline.md`; Figma `ui_v0.1` pages **05 · Situations authoring** and **06 · SceneIQ use-case authoring** |
| Existing PRD | none — not modified |
| Candidate path | `prd/reports/INIT-STRATUM-PLATFORM-CORE-002-prd-think.md` |
| Visual SoT (non-normative) | [05 · Situations authoring](https://www.figma.com/design/3C0bG20lxaQ4Y9OAEkGELh/ui_v0.1?node-id=807-2237) · [06 · SceneIQ use-case authoring](https://www.figma.com/design/3C0bG20lxaQ4Y9OAEkGELh/ui_v0.1?node-id=822-2169) |
| Prior init | `INIT-STRATUM-PLATFORM-CORE-001` (Foundation publish + pin — merged on platform-core) |
| Delivery home | `Sandvik-Common/stratum-platform-core` |
| Score | `/prd-quality` — not written by this skill |

## 1. Job and outcome

- **Job:** A programme can express **where** it operates (Situation attribute values bounded by the workspace pin), **what a model is designed for** on that place (Model run in-scope / out-of-scope claims), and **push catalog gaps upstream** (Promotion: Suggest → Endorse → Approve) — all **pin-safe** so accepting a contribution or publishing a new Foundation release never silently retargets a live workspace.
- **Why now:** CORE-001 delivered Foundation publish + pin on platform-core. Without Situations and Model runs, the Africa open-cast and Finland underground cast stories in [`planning/product-surface-pitch.md`](../../planning/product-surface-pitch.md) cannot be authored or pressure-tested. Model Card / Conformance (CORE-003) has nothing real to attach evidence to.
- **If we do nothing:** Programmes bind to a pin but cannot fill real places or declare model intent; blocked values (e.g. `extreme` dust when pin permits only through `heavy`) force private dictionaries or fake claims; upstream contribution remains untyped; the B+ concurrency story (Africa vs Finland) stays unproven.
- **Kill assumption:** Fails if accepting / approving a Promotion or publishing a new Foundation release **silently retargets** any workspace pin — Africa must keep evaluating the prior release until **explicit retarget**.

## 2. Locked decisions

1. **Programme phase 2 on platform-core.** Delivery surface is **platform-core API + screen-shaped ViewModels** for Situation, Model run, and Promotion. Figma pages 05–06 are the shape contract; no admin-console UI commitment in this INIT (`OQ-01`).
2. **Depends on CORE-001 pin.** Every Situation and Model run is authored against a **workspace pin** to an immutable Foundation release; validation and resolve use the **pin snapshot in Postgres only** — never Git.
3. **Situation values ⊆ pin.** Attribute values must come from operating-field vocabulary permitted on the bound operating context for that pin. Values outside permitted bands are **rejected with a stated reason** (e.g. `extreme` when pin/taxonomy does not permit).
4. **Model run = one model × one situation.** A Model run binds to exactly one Situation on the workspace; roster roles (ML author, Site reviewer, Platform owner, …) are visible and enforced on mutations.
5. **In-scope / out-of-scope claims are falsifiable.** In-scope selections must be adoptable from pin vocabulary; out-of-scope rows declare what the model run is **not designed for**; blocked in-scope selections (catalog gap) expose a **Promotion path** — not silent save.
6. **Promotion workflow is durable in Postgres.** Suggest (ML author) → Endorse (Site reviewer) → Approve (Platform owner) persists state, actor, and timestamp; **pin stays locked** throughout (`PT-10`). GitHub is **not** the Promotion workflow SSOT.
7. **Contribution ≠ adoption (inherits CORE-001 D8/D9).** Approved Promotion does **not** move pins. Qualifying a contribution into a new Foundation release leaves existing pins on prior releases until **explicit retarget** (`PT-11`, `PT-12`, `PT-13`).
8. **Model-run publish binds to current pin in Postgres only** — it does **not** write GitHub or imply Conformance / deploy readiness (`OQ-02`).
9. **Acceptance cast = Africa + Finland.** Done requires Africa happy path (SceneIQ · Open cast · Africa) **and** Finland/Kevitsa concurrency proof (contribution accepted; Africa pin unchanged until retarget).
10. **Stubs where Figma marks them.** **U07d · Promotion in Foundation (Option A)** and **U09 · Running model / Model Card later** are **stub/read-only handoff only** — not Conformance, not Running model, not full Foundation qualify journey.
11. **Distinct enforced actors** on mutations: Site/programme author (Situation values); ML author (Model run + Suggest); Site reviewer (Endorse); Platform owner (Approve); Platform architect (Foundation qualify — stub handoff only in 002).
12. **Store locks inherited, not re-litigated:** Postgres = live SSOT for situations, model runs, proposals, workflow; GitHub only on Foundation RC/publish path when a contribution is later qualified (CORE-001 machinery — **not** required for 002 done per lock 10).

## 3. In scope / non-goals

### In scope

- Situation lifecycle: create under mine type / operating context, fill operating field groups (Environment, Machines, Site features, Operations, Sensing, …), view authored situation.
- Pin-context entry and validation on every Situation save (values ⊆ permitted bands on pin).
- Model run lifecycle: create on a situation, roster visibility, in-scope claim adoption, out-of-scope declaration, blocked-claim → Promotion entry.
- Promotion proposal workflow in Postgres (Suggest → Endorse → Approve) with audit trail.
- Model-run publish recording binding to **current pin / release** (Postgres).
- Explicit pin retarget as the **only** way a workspace adopts a newer Foundation release after upstream acceptance.
- ViewModels projecting Situation, Model run, Promotion, and retarget outcomes for downstream UI.
- Authz enforcement per actor on every mutation above.
- Pressure tests **PT-08–PT-14** (outline §5) demonstrated for Africa + Finland casts.
- Handoff identifiers (example situation id, model-run id) for CORE-003.

### Non-goals (load-bearing)

- Foundation taxonomy authoring from empty (CORE-001).
- Full Foundation qualify / RC publish of approved Promotion (**U07d stub only** — qualify door is read-only handoff, not end-to-end done criteria).
- Model Card authoring, Conformance gate, evidence scores (CORE-003).
- Running model, fleets, telemetry, OTA (CORE-004; **U09 stub only**).
- Promotion as git-PR workflow SSOT (rejected).
- GitHub merge alone publishing Foundation or moving pins (rejected — PT-14).
- Frontend product surface for pages 05–06 in this INIT (unless separately authorized — `OQ-01`).
- Pixel-perfect Figma chrome before pressure-test Acts pass.

## 4. Actors

| Actor | Can actually | Cannot / OQ |
|-------|----------------|-------------|
| **Site / programme author** | Create/edit Situation values on workspace pin | Save values outside pin-permitted bands; retarget pin |
| **ML author** | Create Model run on situation; adopt in-scope claims; **Suggest** Promotion on blocked gap | Endorse or Approve Promotion; qualify into Foundation RC |
| **Site reviewer** | **Endorse** Promotion proposals | Approve Promotion; author Situation without privilege |
| **Platform owner** | **Approve** Promotion proposals; see Promotion outflow | Qualify into Foundation RC (stub in 002); operate Running model |
| **Platform architect** | Read Promotion handoff toward Foundation qualify (**stub U07d**) | Complete Conformance or Running model journeys |
| **Compliance / auditor** | Inspect who suggested/endorsed/approved and when | Mutate domain state |

## 5. Capabilities

| ID | Capability | Journeys covered | Notes |
|----|------------|------------------|-------|
| CAP-01 | Pin-co