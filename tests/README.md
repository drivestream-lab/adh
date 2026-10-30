# Tests for adh

## Structure

```
tests/
  unit/        Pure unit tests — no real infra, no network calls.
               Run: make test
  verify/      Live verify scripts (add per wave; not wired in Makefile).
  _helpers/    Shared fixtures and helpers (e.g. verify preflight).
```

## Running

```bash
make check
make test

# Live verify (integration) — run scripts directly when added:
# docker-compose -f docker/docker-compose.yml up -d
# .venv/bin/python -m tests.verify.verify_health
```
