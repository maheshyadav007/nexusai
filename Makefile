.PHONY: setup dev backend frontend check

setup:
	cd backend && uv sync
	cd frontend && npm ci

backend:
	cd backend && uv run nexusai-backend

frontend:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 backend frontend

check:
	cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run lint-imports && uv run pytest -q
	cd frontend && npm run check
