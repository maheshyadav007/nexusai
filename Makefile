.PHONY: setup dev start serve backend frontend check speed eval-mail

setup:
	cd backend && uv sync
	cd frontend && npm ci

backend:
	cd backend && uv run nexusai-backend

frontend:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 backend frontend

# The fast build, for using the app. Pages compile as they're opened in dev, which feels slow.
start:
	cd frontend && npm run build
	$(MAKE) -j2 backend serve

serve:
	cd frontend && npm start

check:
	cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run lint-imports && uv run pytest -q && uv run pytest -q -m speed
	cd frontend && npm run check

# Builds a 100,000-message mailbox, so it stays out of everyday checks.
speed:
	cd backend && uv run pytest -q -m speed -s

# Judges made-up emails with the connected model, to check the Mail agent's prompts. Uses its tokens.
eval-mail:
	cd backend && uv run python evals/mail_eval.py
