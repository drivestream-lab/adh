# As-built — Hermes collaborator

## Done (ADR 0001 cutover + authoring slice)

| Capability | Status |
|------------|--------|
| Spec + ADR + catalogue projection | live (docs) |
| Catalogue / understand / brief / session / navigator / dispatch / forge | unit-tested |
| `HermesCollaboratorService` + `MetaPmProgrammeService` | wired; `post_promote_walk` **deleted** |
| Validate / post-PM loop | Pass = validate→review→update (cap `pm_max_post_validate_passes`); auto decide+apply inside `pm_auto_decide_validate_passes`; then delta brief → confirm auto-runs impact-map → forge auth. Mid-lane artefacts **local-only** (no GitHub Contents until forge) |
| Authorized forge (`open_draft_pr`) | **live-proven** — fill draft slots, push local PRD/Impact-Map/Resolution/Validation onto `chore/{INIT}-prd` via GitHub App Contents API, then open draft PR via Pulls API (no `gh` CLI). PM lane complete |
| ADH Agents Team OS (`adh_agents`) | **planned** — ADR 0002 + [implementation plan](../plans/adh-agents-implementation-plan.md). Greenfield baton OS; hire `pe` → `read` → `kb`; leverage PM. Codegraph MCP = tool hole on reader |
| PE / Gate‑1 swarm | **not started** — coordinator on Buzz; readers as agents; attest + PM merge |
| KB OKF heads | **not started** — see [adh-kb-heads](../references/adh-kb-heads.md); kb agent writes |
| Validation-Report parse | titled sections (`## Critical (…)` ) + table Finding/Recommendation cells |
| `AuthoringProgrammeService` | `/prd-think` + `/prd-quality` + Hermes-owned promote-judge hop → Buzz brief; no `/prd-critic` |
| LiteLLM authoring prompts (`think`/`quality`/`ask`/`recommend` + cards) | **deleted** |
| Ask/recommend Redis pending + authoring mixin | **deleted** |
| Dual-track doc | **deleted** |

## Verify

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest \
  tests/unit/test_workflow_catalogue.py \
  tests/unit/test_hermes_collaborator.py \
  tests/unit/test_hermes_post_promote.py \
  tests/unit/test_hermes_pm_listener.py \
  tests/unit/test_quality_file_render.py \
  tests/unit/test_prompt_service.py -q
```
