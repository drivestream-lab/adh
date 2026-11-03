# Hermes PM dual-track (Buzz runtime vs prayog skills)

Operator chain and skill procedure stay in
`prayog-skills/docs/pm-lane-think-first.md`. This note locks how ADH Buzz
Hermes relates to those skills **today**.

## Two tracks until a skill runner exists

| Track | What runs today | SSOT for procedure |
|-------|-----------------|--------------------|
| **Buzz / Hermes** | LiteLLM prompts `hermes.pm.think.c1` (first candidate), `hermes.pm.think.c2` (later candidates including C3/C4), `hermes.pm.quality`, plus Hermes **cards** (quality/ask judgement) | Transitional authoring prompts under `src/prompts/` |
| **Cursor / human** | `/prd-think`, `/prd-quality` skills | `prayog-skills/skills/requirements/prd-think`, `prd-quality` |

## Post-promote (Buzz)

After Lead names a think and Hermes copies `prd/{INIT}.md`:

1. Lead replies `validate` (scratch kept until `clean`).
2. Hermes runs prayog skills via `PmSkillRunnerService` (Cursor CLI in meta_root).
3. Hermes posts **ask-shaped decision briefs** for VF findings (question, real life, options, we-recommend + why).
4. Lead answers in Buzz (`VF-01: fix`, `explain`, `accept-recs`, …).
5. Hermes writes `Resolution-{INIT}.md`, runs update/impact skills, awaits manifest/`confirm`.
6. Hermes **never** opens Forge; status says baton ready.

## Explicit debt

- Do **not** add `hermes.pm.think.c3.yaml` / `c4.yaml`. Code picks `c1` when
  `run <= 1`, else `c2`.
- Retire Hermes think/quality **authoring** prompts once a skill runner
  invokes `/prd-think` and `/prd-quality`.
- Keep Hermes **cards** (agentic judgement) after the skill runner lands.
- Quality card = which file is strongest; ask forks = which product choices
  change the pick. While ask is open, naming `C4` does not promote — Lead
  must `skip` (or answer forks) then name the file.
- In-band promote copies the named think file to `prd/{INIT}.md`. Forge does
  not draft; Hermes does not merge; validate starts only when Lead says
  `validate`.
