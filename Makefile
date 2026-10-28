.PHONY: setup check check-ci format format-check lint lint-check types layers test run

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
	.venv/bin/pytest tests/unit/ -v

run:
	.venv/bin/python -m src.main
