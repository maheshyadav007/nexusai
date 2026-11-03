# NexusAI

A local-first AI work OS for corporate employees: mail, documents and notes in one place, with an agent you can see, approve and undo.

Status: in development. The web app comes first, then an Electron desktop app.

| Folder | Contents |
|---|---|
| `docs/` | [Product vision](docs/PRODUCT_VISION.md), [features](docs/FEATURES.md), [architecture](docs/ARCHITECTURE.md), [component plan](docs/COMPONENT_PLAN.md), [tech stack](docs/TECH_STACK.md), [known problems](docs/KNOWN_PROBLEMS.md), design reference |
| `backend/` | Local Python backend: FastAPI, event bus, modules. Managed with `uv` |
| `frontend/` | Next.js UI: theme files, typed client, screens |
| `scripts/` | `dev.mjs`, for setup and running without `make` |
| `archive/` | Old work, reference only |

## Run

Needs [`uv`](https://docs.astral.sh/uv/) and Node 22.

```sh
make setup
make dev      # then open http://127.0.0.1:3000
make check    # lint, types, boundaries, no-hardcoding, tests
```

On Windows, which usually has no `make`, install [uv](https://docs.astral.sh/uv/) and Node, keep the clone at a short path such as `C:\\dev\\nexusai`, and use:

```sh
node scripts/dev.mjs setup
node scripts/dev.mjs       # then open http://127.0.0.1:3000
```

Other checks:

```sh
make speed      # search and lists against a 100,000-message mailbox
make eval-mail  # judges made-up emails with your connected model, and uses its tokens
cd frontend && npx playwright install chromium && npm run test:e2e   # browser tests
```

On first run the app asks where to keep your Home folder, which holds your mail, documents and memory. Set `NEXUSAI_HOME` to use a fixed folder instead.
