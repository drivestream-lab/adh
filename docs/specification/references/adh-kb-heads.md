# OKF knowledge heads (tenant meta)

Programme memory for PE/readers/KB agent. Lives under `{tenant-meta}/knowledge/` (versioned with the meta repo).

## Heads

| Head | Contents | Not for |
|------|----------|---------|
| `foundation/` | Harness/prove/path norms, meta vs app | Full pins, workflow.yaml copy |
| `stacks/{stack}/` | Programme overlay for a prayog stack key (`python-backend`, …) | Full profile / constitution dump |
| `repos/{repo}/` | Entrypoints, pattern pointers, ADR **index** (links), harness notes, watchlist | Full ADR bodies, code dumps |
| `contracts/` | CTR provider→consumer edges, stability notes | Full PRD REQ tables |

Optional later: `platforms/`, `topology/`, `delivery/`, `ops/` — only if heads above overflow.

## Rules

1. **No initiative folders** as SSOT. INITs may appear as footnotes/sources inside a head patch, not as `knowledge/initiatives/{INIT}/`.
2. Enrich via **`adh.kb`** on Buzz baton (typically after PRD merge and/or spec merge) — not silent PE side effects.
3. Readers **read** heads; they do not own writes.
4. Authority for repo architecture remains **ADRs + specs + code**; KB is an accelerator (delete-KB test must still leave architecture recoverable).

## PoC seed (RealWorld)

```text
realworld-meta/knowledge/
  README.md
  foundation.md
  stacks/python-backend.md
  stacks/nextjs-frontend.md
  repos/.gitkeep
  contracts/.gitkeep
```
