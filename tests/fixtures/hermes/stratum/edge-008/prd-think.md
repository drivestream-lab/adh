# INIT-STRATUM-008 — Edge Agent Autrio Join (Identity, Bootstrap, Control and Data Paths)

*Product-authored, engineering-facing | Strict Schema from outline | Owned substrate: `stratum-edge-agent` | DRAFT | August 2026*

**Source outline:** `prd/INIT-STRATUM-008-outline.md`  
**Discovery locks (this draft):** Outline + product discussion August 2026 `(Source: User-confirmed)` except A2/A3 and OQ-01–OQ-06. AI System Requirements **N/A**.

---

## 1. Executive Summary

### Problem Statement

The Edge Agent cannot join Autrio the way Autrio devices are meant to join. It is told in advance where to talk and how to prove itself, while Autrio already has a **device bootstrap service (Setu)** that, after a successful join, tells the device where to connect, what to listen to, where to send data, and how long the session is valid. Join secrets that may **rotate** are also not treated as protected on-device credentials.

### Proposed Solution

On `stratum-edge-agent`, commission the box with **serial** (settings), a **first-run secret** (environment), and the **Setu URL** (settings). **Product intent** is join by **serial only** (no tenant id on the device); that contract is **at-risk until A2 / OQ-01** (same pattern as SC7). On success the agent **persists whatever secret Autrio returns** in a protected store and uses it on the next Setu join `(Source: User-confirmed)`. It uses Autrio’s **short-lived session** on the message path, connecting with **TLS or plain as Autrio’s join response specifies** — **not** mutual device certificates in Phase 1, and the agent does **not** hardcode TLS vs plain. It **listens** on Autrio-named **update** and **command** destinations, and **sends** scraped inference data (after local store) on Autrio-named send destinations. Optional machine serial read **warns** on mismatch **at most once per agent start**; join still uses settings. This **supersedes `INIT-STRATUM-006` only** for identity used at join, how connection is learned, and how control/data destinations are chosen.

### Success Criteria

1. **Named (CAP-01, REQ-01):** Commissioned agent has serial in settings; Autrio join uses that serial `(Source: User-confirmed)`.
2. **Optional check (CAP-01, REQ-02):** If machine serial can be read and differs from settings, operators see a **warning at most once per agent start**; join still uses settings `(Source: User-confirmed)`.
3. **Join (CAP-02, REQ-03):** With serial, first secret, and Setu URL, bootstrap succeeds and returns connection details plus listen/send maps `(Source: User-confirmed)`.
4. **Control (CAP-03, REQ-04):** After join, the agent listens on Autrio-named **update** and **command** destinations; Phase 1 fails if those names are missing `(Source: User-confirmed)`. **Depends on A3 — at-risk until A3/OQ-02 confirmed.**
5. **Data (CAP-04, REQ-05):** Scraped inference metrics can be held locally and sent on Autrio-named send destinations when the link is up `(Source: User-confirmed)`. Missing Au