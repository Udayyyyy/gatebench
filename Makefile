.PHONY: check test audit reproduce

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest

test:
	uv run pytest

audit:
	uv run gatebench audit --output runs/audit

reproduce:
	uv run python scripts/reproduce.py
