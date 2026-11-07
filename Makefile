.PHONY: setup dev start serve backend frontend check speed eval-mail eval-skills test-start test-backend test-serve test-reset

setup:
	cd backend && uv sync
	cd frontend && npm ci

backend:
	cd backend && uv run nexusai-backend

frontend:
	cd frontend && npm run dev

dev:
	@echo "Development mode compiles pages as they open, which feels slow. To use the app, run: make start"
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

# Checks agents load skills when the work calls for it, and only then. Uses the model's tokens, so
# run it only once the spend is agreed. Add --budget to cap it.
eval-skills:
	cd backend && uv run python evals/skill_eval.py

# A second NexusAI for trying things, apart from yours: its own Home, data, sign-ins and secrets,
# all in .test-instance, on http://127.0.0.1:4001. It never touches your Home or your Keychain.
# make test-reset wipes it, so the next make test-start begins at setup again.
TEST_DIR := $(CURDIR)/.test-instance
TEST_DATA := NEXUSAI_APP_DATA=$(TEST_DIR)/app-data

test-start:
	cd frontend && npm run build
	$(MAKE) -j2 test-backend test-serve

test-backend:
	cd backend && $(TEST_DATA) NEXUSAI_HOME=$(TEST_DIR)/home NEXUSAI_SECRETS_TEST_FILE=$(TEST_DIR)/secrets.json NEXUSAI_PORT=4101 uv run nexusai-backend

test-serve:
	cd frontend && $(TEST_DATA) NEXUSAI_DESKTOP_BACKEND_URL=http://127.0.0.1:4101 NEXUSAI_ALLOWED_ORIGINS=http://127.0.0.1:4001,http://localhost:4001 npx next start -p 4001

test-reset:
	rm -rf $(TEST_DIR)
	@echo "The test instance is wiped. Stop it first if it was running, then make test-start."
