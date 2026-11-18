.PHONY: setup check check-ci format format-check lint lint-check types layers test run adh-pm adh-pe adh-read adh-kb adh-dev adh-coder adh-verify desktop-dev desktop-install

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

# Host workers: load `.env`, run in a terminal (or Cursor background shell).
# Progress / trajectory live on Buzz — no monitor_* / run_adh_* wrapper scripts.
adh-pm:
	.venv/bin/python -u -m src.adh_pm_worker

adh-pe:
	.venv/bin/python -u -m src.adh_pe_worker

adh-read:
	.venv/bin/python -u -m src.adh_read_worker

adh-kb:
	.venv/bin/python -u -m src.adh_kb_worker

adh-dev:
	.venv/bin/python -u -m src.adh_dev_worker

adh-coder:
	.venv/bin/python -u -m src.adh_coder_worker

adh-verify:
	.venv/bin/python -u -m src.adh_verify_worker

desktop-dev:
	cd apps/buzz-desktop && npm install && npm run dev

desktop-install:
	bash apps/buzz-desktop/macos/install.sh
