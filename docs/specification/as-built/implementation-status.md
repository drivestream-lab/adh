# As-built — Hermes collaborator

## Done (ADR 0001 cutover + authoring slice)

| Capability | Status |
|------------|--------|
| Spec + ADR + catalogue projection | live (docs) |
| Catalogue / understand / brief / session / navigator / dispatch / forge | unit-tested |
| `HermesCollaboratorService` + `MetaPmProgrammeService` | wired; `post_promote_walk` **deleted** |
| Validate / post-PM loop | Pass = validate→review→update (cap `pm_max_post_validate_passes`); auto decide+apply inside `pm_auto_decide_validate_passes`; then decision-card brief → Lead confirm → Lead-triggered impact-map → forge auth. Mid-lane artefacts **local-only** (no GitHub Contents until forge) |
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
