# ADR 0006 — Hire `adh.verify` (deploy + blackbox + IAC evidence + collaboration)

- **Status:** **Accepted** — locks V.1–V.15 in sole [implementation plan](../plans/adh-agents-implementation-plan.md) (Lead 2026-11-14: human-dev metaphor; collaboration under `ADH_VERIFY_MAX_COLLAB_ROUNDS` default 10; IAC `.env` + schema analysis; branch `feature/coder-hire`)
- **Date:** 2026-11-14
- **Context:** Coder (`adh.coder`) walks YAML through `wave-pr-action` and historically opened `wave-acceptance` without a dedicated deployer/prover. Prayog intends a human to run co-shipped `verify_command` / `make verify` on local Docker and look at DB/logs. That role is **Verify** — not QA. **Locks + tracker:** only [adh-agents-implementation-plan.md](../plans/adh-agents-implementation-plan.md).

## Decision

1. **Hire `adh.verify`** (`VerifyAgent` + `make adh-verify`), same spine as Coder/Dev.
2. **Handoff** — After successful `wave-pr-action`, Coder emits **`verify.wave`** and does **not** own prove/`wave-acceptance` GateOpener. Verify owns deploy → trigger → evidence → GateOpener for `wave-acceptance`.
3. **Human metaphor** — Unit green under Coder; Verify deploys tip to **local Docker/IAC**, runs Coder’s **`make verify` / WM `verify_command`**, observes output, then **substantiates** with multi-source evidence.
4. **IAC analysis** — Verify reads generated/IAC files, discovers **DB schema** and **creds from local IAC `.env`**, **connects**, and runs analysis. Does not invent product HTTP/MQTT clients as primary ingress; does not write product/fixture/driver code.
5. **Collaboration** — On fail: Hermes RCA posts **failures + root cause + feedback** to Coder (`loop-spec`); Coder fixes and re-emits `verify.wave`. Automatic under cap — **no GateOpener per fail**. Cap = **`ADH_VERIFY_MAX_COLLAB_ROUNDS`** (default **10**). Cap → hold. Pass → GateOpener `wave accepted`; then baton Coder for `wave-awaiting-closeout` Pass-2.
6. **Hermes** — `hermes.verify.substantiate` (pass) + `hermes.verify.rca` (fail/collab); same packs human + god.
7. **Guinea pig** — INIT-REALWORLD-001 on `feature/coder-hire`.
8. **Two phases (V.16)** — **Phase 1:** shared **`dev-infra-lab`** (Postgres · Redis · network · LiteLLM + volumes; Kafka/Flink hole later) plus separate **ADH IAC local** (Buzz) and **`realworld-local`** (apps). **Phase 2:** Coder fix + Verify hire. **No faking.** Verify assumes Phase 1 stack present; missing → **hold**. Not an `adh.iac` agent inside this hire unless Lead expands scope.

## Consequences

- Coder fence after wave Draft PR; Verify owns acceptance prove.
- Delivery harness collaboration is the Verify↔Coder loop (named **collaboration**).
- Live Verify prove is **blocked** until IAC-local readiness exists; spine may land in parallel.
- QA / cloud IAC / `adh.iac` agent remain later (or parallel) workstreams — not faked inside Verify.

## Non-goals (this hire)

- `adh.qa` · cloud IAC day-1 · Verify writing fixtures/drivers · fixture-fake prove · auto-pass `/verify` skill · auto-merge · inventing product compose
