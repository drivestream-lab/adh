# INIT-STRATUM-PLATFORM-CORE-002-prd-quality

| Field | Value |
|-------|-------|
| Initiative | INIT-STRATUM-PLATFORM-CORE-002 |
| Date | 2026-09-16 |
| Files | C1 `prd/reports/INIT-STRATUM-PLATFORM-CORE-002-prd-think.md` / C2 `prd/reports/INIT-STRATUM-PLATFORM-CORE-002-prd-think-2.md` |
| Brief | `prd/INIT-STRATUM-PLATFORM-CORE-002-outline.md` |
| Companions | none (prd-critic not installed) |
| **Handover** | C1: no; C2: yes |
| Rank | C2-wins — **not** the validate signal |

## Handover

`yes` = zero material FAILs on that file → may promote **that named file**, then `/validate-requirements`. `no` = keep looping `/prd-think`.

| File | Material FAILs | Handover | Blocking bars |
|------|----------------|----------|---------------|
| C1 `INIT-STRATUM-PLATFORM-CORE-002-prd-think.md` | 1 | no | B11 |
| C2 `INIT-STRATUM-PLATFORM-CORE-002-prd-think-2.md` | 0 | yes | — |

Jobs differ (C1: Approve+stub U07d is enough; C2: approved gap must enter Foundation authoring). Human picks which named file to promote — rank does not auto-pick.

## Independent scores

### C1 `INIT-STRATUM-PLATFORM-CORE-002-prd-think.md`

Material FAIL count: 1  
Handover: no

| Bar | Result | Material FAIL? | Evidence (id + quote) |
|-----|--------|----------------|------------------------|
| B1 Job | PASS | | §1 Job: “express where it operates… Model run… Promotion… pin-safe”; Kill: “silently retargets any workspace pin” |
| B2 CAP→REQ | PASS | | CAP-01…CAP-13 each have ≥1 REQ; every REQ-01…22 cites a CAP |
| B3 Observable | PASS | | e.g. REQ-03 condition “Value outside permitted band” → result “Save refused with named field, value, and reason” + evidence `live J-04 · CAP-02` |
| B4 Negative paths | PASS | | §7 covers out-of-pin, blocked claim, unauthorized (REQ-19), pin-unchanged (REQ-11/14), GH merge (REQ-22); CTR-05 errors “Wrong state; wrong actor” |
| B5 Actors | PASS | | §4 Site author / ML author / Site reviewer / Platform owner / Platform architect with Can / Cannot |
| B6 Seams | PASS | | CTR-01…CTR-07: logical operation + field meaning + errors (e.g. CTR-05 Promotion transitions) |
| B7 NFR | PASS | no | §9 all eight areas specified or N/A |
| B8 Assumptions | PASS | | A-01…A-04 status + Dependent REQs + Default if false |
| B9 OQ | PASS | | OQ-01…OQ-06 owner, Blocking, Required-by, Default if deferred |
| B10 Non-goals | PASS | | §3 U07d stub, CORE-003/004, FE out, GH-as-workflow rejected |
| B11 WHAT not HOW | FAIL | yes | REQ-13 observable: “Published model run shows pin/release binding **in Postgres**; **no GitHub write**” — store technology in the REQ forces solution prescription |
| B12 Whole-product | PASS | | §12 note: J-13–J-15 concurrency/retarget “page 05–06 frames do not walk”; Compliance auditor in §4 |
| B13 Impact-map ready | PASS | no | Delivery home `stratum-platform-core`; CAP-01…13 matchable to platform-core owns |
| B14 CAP ↔ journey | PASS | | Every CAP lists ≥1 J-*; every J-01…16 cites Caps exercised |
| B15 Live-prove shaped | PASS | | Live REQs cite CAP and/or J (e.g. REQ-11 `live J-11 · CAP-07`) |

#### Spec-lane simulation

- Exact Promotion proposal fields → already OQ-01.
- Store engine for model-run publish → **not OQ’d**; REQ-13 names Postgres → B11 FAIL / would force `needs-input` or over-constrain eng.

### C2 `INIT-STRATUM-PLATFORM-CORE-002-prd-think-2.md`

Material FAIL count: 0  
Handover: yes

| Bar | Result | Material FAIL? | Evidence (id + quote) |
|-----|--------|----------------|------------------------|
| B1 Job | PASS | | §1 Job includes “enter Foundation authoring… without moving any live pin”; Kill: “approved Promotion cannot enter Foundation authoring… even when Suggest → Endorse → Approve succeeded” |
| B2 CAP→REQ | PASS | | CAP-01…CAP-10 each ≥1 REQ; REQ-01…24 each cite a CAP |
| B3 Observable | PASS | | e.g. REQ-13: condition `Proposal approved` → “Foundation catalog draft / RC hando