.PHONY: setup check check-ci format format-check lint lint-check types layers test run desktop-dev desktop-install orch-spawn orch-merge orch-kill

# Quality ingress is Makefile-only: `make check` then `make test`.

setup:
	@bash scripts/setup_dev.sh

check: format lint types layers

check-ci: format-check lint-check types layers

format:
	.venv/bin/black --line-length 100 src/ tests/

format-check:
	.venv/bin/black --check --line-length 100 src/ tests/

lint:
	.venv/bin/ruff check --fix src/ tests/

lint-check:
	.venv/bin/ruff check src/ tests/

types:
	.venv/bin/pyright

layers:
	.venv/bin/lint-imports

test:
	env -u PYTHONPATH PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest tests/unit/ -v -p pytest_asyncio.plugin

run:
	.venv/bin/python -m src.main

orch-spawn:
	ORCH_ENABLE_SPAWN=true .venv/bin/python -m src.orchestrator spawn

orch-merge:
	.venv/bin/python -m src.orchestrator merge

orch-kill:
	ORCH_ENABLE_SPAWN=true ORCH_CURSOR_TIMEOUT_SECONDS=420 .venv/bin/python -m src.orchestrator kill

desktop-dev:
	cd apps/buzz-desktop && npm install && npm run dev

desktop-install:
	bash apps/buzz-desktop/macos/install.sh
