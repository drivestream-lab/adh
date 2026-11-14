# INIT-STRATUM-HITL-WEB-001-prd-quality

| Field | Value |
|-------|-------|
| Initiative | INIT-STRATUM-HITL-WEB-001 |
| Date | 2026-09-15 |
| Files | C1 `prd/reports/INIT-STRATUM-HITL-WEB-001-prd-think.md` / C2 `prd/reports/INIT-STRATUM-HITL-WEB-001-prd-think-2.md` |
| Brief | Conversation (Figma page 04 Platform authoring; greenfield FE; integrate login + Unit + platform-core) |
| Companions | prd-critic / none |
| **Handover** | C1: yes; C2: yes |
| Rank | C2-wins — **not** the validate signal |

## Handover

`yes` = zero material FAILs on that file → may promote **that named file**, then `/validate-requirements`. `no` = keep looping `/prd-think`.

| File | Material FAILs | Handover | Blocking bars |
|------|----------------|----------|---------------|
| C1 `INIT-STRATUM-HITL-WEB-001-prd-think.md` | 0 | yes | — |
| C2 `INIT-STRATUM-HITL-WEB-001-prd-think-2.md` | 0 | yes | — |

Both qualify. Jobs differ: C1 anchors acceptance on **full page-04 frame set**; C2 anchors on **Open-pit ready gate (C7)** with frames still in scope. Human picks which file to promote.

## Independent scores

### C1 `INIT-STRATUM-HITL-WEB-001-prd-think.md`

Material FAIL count: 0  
Handover: yes

| Bar | Result | Material FAIL? | Evidence (id + quote) |
|-----|--------|----------------|------------------------|
| B1 Job | PASS | | §1: "people with different roles can log in and complete **Foundation Platform authoring** … against **current `stratum-platform-core`** … through the **Situations stub (P31)**"; why-now and if-we-do-nothing present |
| B2 CAP→REQ | PASS | | CAP-01→REQ-01/02/14; CAP-02→REQ-03/04/13; CAP-03→REQ-05; CAP-04→REQ-06; CAP-05→REQ-07; CAP-06→REQ-08; CAP-07→REQ-09; CAP-08→REQ-11; CAP-09→REQ-10; CAP-10→REQ-12 — every REQ cites a CAP |
| B3 Observable | PASS | | REQ-09: Condition "publish/pin preconditions satisfied in backend" → Observable "UI shows successful publish/pin outcomes **only when platform-core confirms**" → Evidence `live J-06 · CAP-07` |
| B4 Negative paths | PASS | | §7: REQ-02 unauthorized deny; REQ-12 backend down / promotion reject; REQ-09 publish preconditions; REQ-10 pin incomplete — plus J-02/J-04/J-05 abandon edges for validation/partial |
| B5 Actors | PASS | | §4: Platform Architecture completes ready gate; restricted roles denied; actions tied to privileges |
| B6 Seams | PASS | | CTR-01–CTR-06: stratum-platform-core ↔ stratum-hitl-web with logical ops, field meaning, errors |
| B7 NFR | PASS | | §9: security, reliability, performance, observability, privacy, migration, rollback, operations — each specified |
| B8 Assumptions | PASS | | A-01: Status "assumed (user-confirmed backend in place)"; Dependent REQ-05–REQ-11; Default "Park blocked surfaces as OQ; do not fake in UI" |
| B9 OQ | PASS | | OQ-01: Owner PM+PE; Blocking yes; Required-by spec-draft; Default "Use backend-authored roles present in env" |
| B10 Non-goals | PASS | | §3: Situations/Model-run depth, FE-owned domain rules, purged process PRD — each with why |
| B11 WHAT not HOW | PASS | | REQ rows avoid routes/modules; domain terms (ViewModel, Figma SoT) are product vocabulary not implementation |
| B12 Whole-product | PASS | | J-08 restricted-role deny and J-09 backend fail-closed explicitly "brief did not list" |
| B13 Impact-map ready | PASS | | CAPs map to `stratum-hitl-web` (UI) consuming `stratum-platform-core` per delivery home |
| B14 CAP ↔ journey | PASS | | CAP-01→J-01/J-08; every journey row lists Caps exercised; CAP-10→J-09/J-08 |
| B15 Live-prove shaped | PASS | | REQ-05 Evidence `live J-02 · CAP-03`; REQ-01 `live J-01 · CAP-01` — live cites CAP and J |

#### Spec-lane simulation

Guess-points already parked as OQ-*:

- Role/privilege matrix for v1 → OQ-01 (blocking, default provided)
- Frame delivery vs gate subset → OQ-04 (blocking, default all P##)
- Missing BE operation policy → OQ-05 (blocking, default hide/disable)

No orphan guess requiring new OQ.

### 