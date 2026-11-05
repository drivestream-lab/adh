# Hermes delivery collaborator

## Intent

Hermes is the Buzz delivery collaborator for `sdd-delivery/v2`. It helps Lead the way a human uses Cursor: read artefacts, ask for recommendations and examples, judge, then tell the agent to execute.

## Loop

1. **Understand** Lead message against the workflow catalogue + current session (clarify missing slots such as `INIT-…`).
2. **Brief** at every human checkpoint and judgment-shaped skill outcome: question, real-life example, options + consequences, we-recommend + why, exact reply tokens.
3. **Judge** — Lead replies at Lead-owned gates. Hermes may decide on initial validate-findings passes (see below) after posting recommend+why. Forge / `authorization: explicit` nodes never auto-run.
4. **Execute** — after judgment / Hermes first-pass VF decisions / explicit “go ahead”, run the next catalogue node: skill via skill runner, or forge/GitHub for `external-action`.

## Catalogue

- Load pinned `prayog-skills/workflow.yaml` and skill `SKILL.md` index.
- Resolve `next = outcomes[stage][outcome]` only from that document.
- Do not hardcode skill ids, checkpoint purposes, or forge actions in ADH.

## Surfaces

- **Cards / briefs** for decisions.
- **Conversation** for clarify and control (“post-pm for INIT-…”, “go ahead publish the PR”).
- Durable state remains artefacts + handoff; Redis/session is runtime only.

## Authoring PM value (promote gate)

Hermes is an agentic PM collaborator for Lead — not a skill router waiting on companions:

- After `/prd-think` (+ `/prd-quality` scorecard evidence), Hermes writes a **product promote card** (`prd/reports/{INIT}-hermes-promote-brief.md`): **recommend / bluf / buying / not buying / choose-another-if / example** (≤30s PM skim, product language only).
- That card is what the human PM sees on Buzz to pick among candidates.
- Hermes does **not** install, invoke, or wait for `/prd-critic`. Quality’s Secondary critic section is omitted.
- Lead still names the file (`C#` / skip); Hermes never auto-promotes.

## Validate / post-PM PM value (think-lane parity)

Mirror authoring (`pm_max_think_runs` → quality → Hermes promote-brief → one Lead gate):

1. **One pass** = `/validate-requirements` → Hermes review findings (WHYs) → `/update-documents` (think-lane parity). Cap = `pm_max_post_validate_passes` (default 2; also `pm_auto_decide_validate_passes` for Hermes-owned decide+apply inside that budget).
2. **Mid-lane writes stay local** — promote PRD + Resolution write the tenant meta workspace only. No GitHub Contents publish until authorized forge (`external-writes-require-authorization`).
3. **Post-pass proceed/hold card** — after the validate budget (or clean), Hermes writes `prd/reports/{INIT}-hermes-post-pm-brief.md` as a **delta readout** (changed / deferred / still risky) from Validation + Resolution — **not** a re-pitch of the job. Human PM **confirm** (proceed) or **revise** (hold / fix PRD offline).
4. **`confirm` auto-runs Impact-Map** — accepting the brief means the post-PM lane is good; Hermes runs `/prd-impact-map` immediately (no second Buzz hop). Impact-Map means the PRD is ready for draft PR.
5. **Draft PR auth** — after Impact-Map, Hermes opens `prd-pr-action` (`open_draft_pr`, `authorization: explicit`). Never auto-runs. On authorize, forge seeds `body_path` / `head_branch`, pushes the local PRD + reports onto the draft head via **GitHub App Contents API**, then opens the draft PR via the **Pulls API** (no `gh` CLI). Mid-lane artefacts stay **local-only** until that hop.
6. **Engg / Gate‑1 onward** — multi-agent team on Buzz (`adh.pe`, `adh.read`, `adh.kb`, …). See [`adh-agents-team-os.md`](adh-agents-team-os.md) and [ADR 0002](../adr/0002-adh-agents-team-os.md). PM emits a PE baton after draft PR; does not in-process dig repos.

## Cutover debt (must delete)

See ADR 0001. Dual-track Buzz authoring prompts and walk FSMs are transitional until the orchestrator flip removes them.
