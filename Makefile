.PHONY: setup check check-ci format format-check lint lint-check types layers test run adh-pm adh-pe adh-read adh-kb adh-dev desktop-dev desktop-install

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

adh-pm:
	@bash scripts/run_adh_pm_worker.sh

adh-pe:
	@bash scripts/run_adh_pe_worker.sh

adh-read:
	@bash scripts/run_adh_read_worker.sh

adh-kb:
	@bash scripts/run_adh_kb_worker.sh

adh-dev:
	@bash scripts/run_adh_dev_worker.sh

desktop-dev:
	cd apps/buzz-desktop && npm install && npm run dev

desktop-install:
	bash apps/buzz-desktop/macos/install.sh
