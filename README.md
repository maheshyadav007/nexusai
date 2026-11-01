# NexusAI

A local-first AI work OS for corporate employees: mail, documents and notes in one place, with an agent you can see, approve and undo.

Status: in development. The web app comes first, then an Electron desktop app.

| Folder | Contents |
|---|---|
| `docs/` | [Product vision](docs/PRODUCT_VISION.md), [features](docs/FEATURES.md), [architecture](docs/ARCHITECTURE.md), [component plan](docs/COMPONENT_PLAN.md), [tech stack](docs/TECH_STACK.md), design reference |
| `backend/` | Local Python backend: FastAPI, event bus, modules. Managed with `uv` |
| `frontend/` | Next.js UI: theme files, typed client, screens |
| `archive/` | Old work, reference only |

## Run

Needs [`uv`](https://docs.astral.sh/uv/) and Node 22.

```sh
make setup
make dev      # then open http://127.0.0.1:3000
make check    # lint, types, boundaries, no-hardcoding, tests
```

Browser tests: `cd frontend && npx playwright install chromium && npm run test:e2e`.

Development data goes in `backend/.dev-home/`. Set `NEXUSAI_HOME` to use another folder.
