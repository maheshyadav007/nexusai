# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

NexusAI is a local-first AI work OS (mail, documents, notes) with agents whose work is visible, approvable and undoable. A Next.js UI (`frontend/`, port 4000) talks to a local Python backend (`backend/`, FastAPI, port 4100). `desktop/` is the Electron wrapper. `archive/` is old work, for reference only; don't edit or import from it.

## Commands

Needs `uv` and Node 22 (`.nvmrc`). On Windows without `make`, use `node scripts/dev.mjs setup|start`.

```sh
make setup        # uv sync + npm ci
make start        # production build, then backend + frontend (use this to try the app)
make dev          # dev servers; pages compile on first open, so it's slow
make check        # everything CI-like: ruff format/lint, mypy --strict, import-linter, pytest, speed tests, frontend check
make speed        # 100,000-message mailbox speed targets (pytest -m speed)
make test-start   # a second instance on 4001/4101 with its own Home and secrets in .test-instance/
make test-start COMPANY=1   # also runs a fake company POP3/SMTP server (sign in admin/admin)
make test-reset   # wipe .test-instance/
```

Backend (from `backend/`):

```sh
uv run pytest -q tests/test_mail_sync.py              # one file
uv run pytest -q tests/test_mail_sync.py::test_name   # one test
uv run pytest -q -k folders                           # by keyword
uv run ruff format . && uv run ruff check . && uv run mypy && uv run lint-imports
```

`pytest` skips the `speed` marker by default. `tests/conftest.py` isolates app data, ignores the developer's `.env`, and blocks model downloads. Fakes for servers and models live in `tests/` (`fake_chatgpt.py`, `fake_mail.py`, `fake_pop3.py`, `fake_mcp.py`, `company_server.py`).

Frontend (from `frontend/`):

```sh
npm run check         # typecheck + no-hardcode check + boundaries check + vitest
npx vitest run tests/theme.test.ts
npm run test:e2e      # Playwright (needs: npx playwright install chromium)
npm run contracts     # regenerate ui/client/contracts.generated.ts from backend Pydantic contracts
npm run theme         # regenerate theme output (runs automatically before dev/build/typecheck)
```

Desktop (from `desktop/`): `npm test`. Releases and Windows CI: `docs/WINDOWS_RELEASE_GUIDE.md`, `./desktop.sh ci-trigger`.

**Evals** (`make eval-mail`, `make eval-skills`, `backend/evals/*.py`) run on the real model and spend the user's ChatGPT allowance. Don't run them without asking. Tests with the fake model are always fine. See `docs/EVALS.md`. Any throwaway backend or scratch Home must set `NEXUSAI_SECRETS_TEST_FILE`, or it reads the real Keychain sign-ins and spends the real allowance.

## Architecture

The rules are in `docs/ARCHITECTURE.md` §1 and are checked in review. The ones that shape most code:

- **No polling inside the app.** Changes emit events and listeners react. The UI gets events over SSE (`api/sse.py`), and they mark TanStack Query data out of date.
- **Modules talk only through contracts.** Commands ("do this"), queries ("tell me this") and events ("this happened") are Pydantic models in `backend/src/nexusai/contracts/`. TypeScript types are generated from them (`npm run contracts`), so change the Pydantic model first.
- **One door each** for model calls (`modules/agent/gateway.py`: masking, rate pacing, logging), tool calls (permissions, approvals, `modules/agent/policy.py`, `guard.py`) and DB writes (repository + transaction that saves the change and its durable event together).
- **State is an explicit state machine** (sessions, mail sync, approvals), never a set of booleans.
- **Every bug fix adds a test.** Dependency versions are pinned exactly.

### Backend layers (`backend/src/nexusai/`)

Imports go one way, enforced by import-linter: `api → modules → kernel → contracts`. `kernel` and `contracts` hold no product logic.

- `kernel/`: event bus (durable events in the same transaction as the change, live events not saved), SQLite/SQLCipher database with numbered forward-only migrations, config (`defaults.toml`), Home folder, secrets/Keychain, vault, logging (structlog JSON with `traceId`).
- `kernel/module.py`: the `Module` class. A module registers `@m.command(...)`, `@m.query(...)` and `@m.on("event.pattern", ...)` handlers. Modules don't read each other's tables.
- `modules/`: `mail` (IMAP/POP3/PST sync, store with FTS5 search and `from:`/`is:` operators, sorting, outgoing), `agent`, `documents`, `semantic` (local ONNX embeddings, separate index files), `planner`, `panels`, `notifications`, `connectors` (MCP), `models`, `settings`, `onboarding`, `system`.
- `api/app.py` wires modules into FastAPI. `api/security.py` keeps the server on 127.0.0.1, checks Host/Origin and the install token.

### Agents (`modules/agent/`)

- Agent definitions are TOML in `agents/` with prompts in `prompts/*.md` (trigger prompts in `prompts/triggers/`). Built-in skills are in `shipped_skills/`.
- Typed messages, events and schedules (`schedule.due`) all start runs through `SessionRuntime.dispatch` (`runtime.py`). Each emits `agent.triggered`, and `trigger_runs` prevents a replayed event from starting a run twice.
- What the model is sent is decided per run in `context.py` (trim by default, compaction is config). Chat display comes from `agent_parts` and is never shortened. Trigger data (such as an email body) goes beside the message for that run only.
- `knowledge.py` builds what the Mail agent knows (profile, corrections, `signals.py` counts, memory, scoped facts, approved preferences, the email last and least trusted). The "What it knows" page uses the same builder.
- `providers.py` (`ReplyReader`) parses streamed replies, including written tool calls on servers without tool calling. Multi-agent coordination goes through `channel.py`/`team.py`.
- The target is good results from a low-capability model, so routing, small prompts, clear tool errors (`tool_errors.py`) and memory matter more than prompt cleverness.

### Frontend (`frontend/`)

- `app/` holds Next.js routes. `ui/` holds everything else. This Next.js version has breaking changes, so read `node_modules/next/dist/docs/` before writing Next-specific code (see `frontend/AGENTS.md`).
- Layers run `features → shell → primitives → theme`, enforced by `scripts/check-boundaries.mjs`. Primitives can't import `client`.
- **One door for components:** screens use `ui/primitives/*`, which wrap Radix and similar libraries. To swap a component, edit its primitive.
- **No hardcoding** (`scripts/check-no-hardcode.mjs`): colors, sizes and spacing come only from theme files (`ui/theme/themes/*.json`, generated by `ui/theme/generate.ts`). User-facing text comes only from `ui/strings/en.json`. It also bans `transition-all`, `uppercase`, heavy font weights, looping animations and gradients (see `ui/DESIGN_DIRECTION.md`).
- Features reach the backend only through the typed client in `ui/client/`, never by calling `fetch` directly.

## Working conventions

- UI or UX changes need a mockup the user approves before you build them. In a plan or review, propose and don't build until told.
- Test mail features against the real Gmail account and the real model when the user asks for that. Never delete anything on Google's server.
- Finish features fully, so the natural next step happens by itself. Work in small steps and keep updates short.
- Plans and feature specs live in `docs/` (`FEATURES.md`, `TODO.md`, `*_PLAN.md`). Read the relevant plan before working on an area.
