# NexusAI

A local-first AI work OS for corporate employees: mail, documents and notes in one place, with an agent you can see, approve and undo.

Status: in development. The web app comes first, then an Electron desktop app.

| Folder | Contents |
|---|---|
| `docs/` | [Product vision](docs/PRODUCT_VISION.md), [features](docs/FEATURES.md), [architecture](docs/ARCHITECTURE.md), [agents and categories](docs/AGENTS_AND_CATEGORIES.md), [component plan](docs/COMPONENT_PLAN.md), [tech stack](docs/TECH_STACK.md), [known problems](docs/KNOWN_PROBLEMS.md), [identity plan](docs/IDENTITY_PLAN.md), design reference |
| `backend/` | Local Python backend: FastAPI, event bus, modules. Managed with `uv` |
| `frontend/` | Next.js UI: theme files, typed client, screens |
| `scripts/` | `dev.mjs`, for setup and running without `make` |
| `archive/` | Old work, reference only |

## Email agents

Mail judgement, Your brief, scheduled work and chat share scoped prompt context. Feedback becomes reviewable instructions under **Prompts and memory → Preferences**, with scope checks, read-only AI previews, expiry and version restore. Today keeps its name. Headings and navigation use Space Grotesk; reading text uses Inter.

See the [email-agent implementation and verification record](docs/EMAIL_AGENT_IMPLEMENTATION.md) and [audit baseline](docs/EMAIL_AGENT_AUDIT_2026-11-04.md). Model-weight training is outside this feedback loop.

## Run

Needs [`uv`](https://docs.astral.sh/uv/) and Node 22.

```sh
make setup
make start    # for using the app, then open http://127.0.0.1:4000
make dev      # for working on the code. Pages compile as they're opened, so clicks are slower
make check    # lint, types, boundaries, no-hardcoding, tests
```

On Windows, which usually has no `make`, install [uv](https://docs.astral.sh/uv/) and Node, keep the clone at a short path such as `C:\\dev\\nexusai`, and use:

```sh
node scripts/dev.mjs setup
node scripts/dev.mjs start # then open http://127.0.0.1:4000
```

### Company install

To set the model and mail servers once, so people only see their username, password and the model names:

```sh
cp .env.example .env    # then fill it in, and restart the app
```

| Setting | For | Default |
|---|---|---|
| `NEXUSAI_MODEL_URL` | Model server, `http://` or `https://`, ending in `/v1` | Not set: people connect ChatGPT or enter a server |
| `NEXUSAI_MODEL_API_KEY` | Its key | None |
| `NEXUSAI_MODEL_NAMES` | Models to offer, separated by commas. The first is the default | The server's own list |
| `NEXUSAI_MODEL_TOOLS` | Whether the server supports tool calling | `false` |
| `NEXUSAI_MODEL_CALLS_PER_MINUTE` | Model calls allowed in a minute, across every agent | No limit of its own. It still slows down when the server says to |
| `NEXUSAI_MAIL_HOST` | Mail server | Not set: people enter a server or use Gmail |
| `NEXUSAI_MAIL_PROTOCOL` | `pop3` or `imap` | `pop3` |
| `NEXUSAI_MAIL_PORT`, `NEXUSAI_MAIL_SECURE` | Incoming port, and whether it uses TLS | `995`, `true` |
| `NEXUSAI_MAIL_VERIFY_CERT` | Set to `false` for a company's own certificate | `true` |
| `NEXUSAI_SMTP_HOST` | Sending server | The mail server |
| `NEXUSAI_SMTP_PORT`, `NEXUSAI_SMTP_SECURE` | Sending port, and whether it uses TLS | `25`, `false` |
| `NEXUSAI_MAIL_DOMAIN` | Makes the address for a login with no `@`: `name` becomes `name@domain` | None |

Real environment variables win over the file. A Gmail login still goes to Gmail over IMAP. PST imports keep their folders with either protocol.

POP3 has one mailbox, so read marks, flags, archiving and sent mail stay on this computer. See [known problems](docs/KNOWN_PROBLEMS.md#pop3-and-company-servers).

Other checks:

```sh
make speed      # search and lists against a 100,000-message mailbox
make eval-mail  # judges made-up emails with your connected model, and uses its tokens
cd frontend && npx playwright install chromium && npm run test:e2e   # browser tests
```

On first run the app asks where to keep your Home folder, which holds your mail, documents and memory. Set `NEXUSAI_HOME` to use a fixed folder instead.

The app runs on port 4000 and its backend on 4100. From another machine on a private network, open `http://<machine-ip>:4000`, with no setup and no login yet, so keep it to test machines for now. To use a machine name or public address, list it in `NEXUSAI_ALLOWED_ORIGINS`, separated by commas, for example `http://mybox.local:4000`.

## Desktop validation and releases

The [desktop manual](docs/WINDOWS_RELEASE_GUIDE.md) covers generic GitHub-hosted Windows build/install/update tests, a private deployment customization layer, and internal releases. Trigger generic validation with `./desktop.sh ci-trigger`; internal endpoints and credentials stay in local profiles rather than application source. See [deployment customization](deployment/README.md) for the Linux-to-Windows handoff. Windows CI and target-device acceptance remain required before distribution.
