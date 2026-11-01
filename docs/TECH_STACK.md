# NexusAI Tech Stack

Living record of the technology choices for NexusAI. Add a row or section whenever a decision is made, and update the status when something moves from planned to in use.

Status legend: **In use** (in the repo today) · **Decided** (agreed, not built yet) · **Considered** (evaluated, not chosen)

## Goals and constraints

- Primary target is **corporate Windows** (10/11, likely no admin rights, corporate proxy, antivirus/AppLocker).
- Development and most testing happen on **macOS only**; Windows is reached through a VM and CI.
- The app should feel native on both platforms while sharing one codebase.
- **Build order: web app first** (Next.js UI + local Python backend), then Electron as a wrapper.
- UI design reference: [`design/NexusAI v9.dc.html`](design/NexusAI%20v9.dc.html).

## Decisions

### Desktop shell

| Choice | Status | Why |
|---|---|---|
| **Electron** | Decided, later | Added after the web app. Ships the same Chromium engine on macOS and Windows, so what we test on Mac matches what Windows users see. Trusted in enterprises (VS Code, Teams, Slack). |
| Tauri | Considered | Smaller and lighter, but renders with WebKit on Mac and WebView2 on Windows, so Mac testing would not be representative. |
| Native (WinUI / SwiftUI) | Considered | Two codebases, and the Windows one could not be tested locally. |
| Python desktop UI (pywebview, Flet, PySide) | Considered | pywebview has the same engine split as Tauri; loses the web UI stack. Python is used for the backend only. |

### UI

| Choice | Status | Notes |
|---|---|---|
| Next.js (App Router) | In use | Local server for the web build. Electron later uses `output: 'export'` to load local files. |
| React + TypeScript | In use | TypeScript across UI, preload and main process. |
| Tailwind CSS | In use | Re-theme to the v9 palette. Colors as CSS variables so light, dark and accent themes switch instantly. v9 defines light only; dark must be designed. |
| Zustand | In use | UI-only state. |
| TanStack Query + Virtual | Decided | Backend data in the UI, refreshed by events; virtualized long lists. |
| Drag-and-drop library (such as `dnd-kit`) | Considered | For panels and sidebar; must support keyboard dragging. |
| Framer Motion, lucide-react, Radix Slot, react-markdown | In use | Animation, icons, primitives, markdown rendering. |
| Bundled fonts (Instrument Sans, Instrument Serif, JetBrains Mono; Space Grotesk available) | In use. Each theme chooses from the font catalog | Loaded with `next/font/google`, which downloads them at build time and serves them locally, so there are no runtime calls to Google Fonts (corporate proxies often block them). Fallbacks: Segoe UI Variable (Windows), SF Pro (macOS). |
| Own component set, built on tokens | Decided | Radix primitives for behaviour; Beautiful UI, free AICSS and Amicro adapted where licenses allow; everything restyled to our theme. See [`COMPONENT_PLAN.md`](COMPONENT_PLAN.md). |
| Radix UI primitives | Decided | Accessible, unstyled Dialog, Menu, Popover, Tabs, Tooltip, Select and Switch. |
| Theme files + CSS variables | Decided | All visual values live in `ui/theme/themes/*.json`. Build checks reject hardcoded colors and sizes. |

### Backend

| Choice | Status | Notes |
|---|---|---|
| **Python + `uv`** | Decided | `uv` manages Python, dependencies and the lockfile. Replaces Node as the backend. |
| FastAPI + Uvicorn | Decided | Local HTTP API on `127.0.0.1`. |
| Server-Sent Events | Decided | Pushes events to the UI, with catch-up by sequence number after a reconnect. |
| Pydantic | Decided | Validates commands, queries, events and external data at every boundary; TypeScript types generated from it. |
| SQLite event log | Decided | Own event bus. Durable events saved in the same transaction as the data change; live events not saved. |
| SQLite, SQLCipher for encryption | Decided | Standard `sqlite3` during early stages, encrypted build added with `APP-9`. Stored under `system/` in the NexusAI Home. |
| `structlog` | Decided | Structured logs with trace IDs. |
| pytest, ruff, `import-linter` | Decided | Tests, lint, and a build check for module boundaries. |

### Electron architecture (later)

| Choice | Status | Notes |
|---|---|---|
| Main process in TypeScript | Decided, later | Kept thin: windows, tray, notifications, global shortcuts, launching the Python backend. |
| Python backend as a sidecar | Decided, later | Uses a bundled standalone Python, not a frozen executable, to reduce antivirus flags. Test early on a corporate laptop. |
| Zod | Decided | Validates theme files and API responses in the UI. |
| Preload + `contextBridge` typed IPC | Decided | `contextIsolation: true`, `nodeIntegration: false`; the UI only sees a small typed API. |
| electron-builder | Decided | One config produces macOS `.dmg` and Windows installers. Windows: **per-user NSIS** installer (no admin needed). |
| Credentials | Decided | OS credential store through Python `keyring`. |
| Auto-update (`electron-updater`) | Decided | Details depend on where corporate builds are hosted. |

### Agent runtime

| Choice | Status | Notes |
|---|---|---|
| **LangChain + LangGraph (Python)** | Decided | Runs in the Agent host process. LangGraph gives parallel sessions, resume after restart, and pausing for approval cards. Exact versions pinned in `uv.lock`. |
| `langgraph-checkpoint-sqlite` | Decided | Saves session state in SQLite under `system/`. |
| `langchain-mcp-adapters` | Decided | Exposes MCP connectors to the agent as tools. |
| Custom LangChain chat model for the internal API | Decided | Needed because the current internal API has no tool calling; holds the JSON fallback. |
| Prompt builder and memory store | Decided | Our code. Prompts and memory are markdown files in Home, indexed in SQLite. LangGraph's own store is not the source of truth, so users can read and edit them. |
| Sensitive data mapper | Decided | Our code, at a single model gateway: masks outgoing text, restores streamed output and tool call arguments. Rules are editable; token map lives in the encrypted database. |
| Work board and agent channel | Decided | Our code: SQLite tables under `system/`, read and written through app tools, so all sessions share one source and every message is logged. |
| Policy layer around every tool | Decided | Our code, not LangChain's: autonomy, permissions, approvals and logging all run before a tool executes. |

### Native feel

| Platform | Approach |
|---|---|
| macOS | `titleBarStyle: 'hiddenInset'`, `vibrancy`, menu-bar icon, ⌘ shortcuts |
| Windows 11 | `backgroundMaterial: 'mica'`, `titleBarOverlay` (native window buttons), system tray, Ctrl shortcuts, Windows-style context menus |
| Both | `CmdOrCtrl` accelerators, native notifications, single-instance lock, launch at login; layout must work at 1366/1536 px widths with 125–150% scaling |

### Testing

| Choice | Status | Notes |
|---|---|---|
| Vitest | Decided | UI unit tests, alongside pytest for the backend. |
| No-hardcoding check | Decided | Our own script in `frontend/scripts`; fails the build on hardcoded colors, sizes and JSX text. |
| Playwright, headless Chromium | Decided | Main test loop for the web app; representative because Electron is Chromium too. |
| Playwright `_electron.launch()` | Decided | Tests the packaged Electron app on Mac locally and on Windows in CI. |
| GitHub Actions `windows-latest` | Decided | Builds the Windows installer and runs the Playwright suite on every push. |
| Windows 11 Arm VM (Parallels, or UTM) | Decided | Manual pre-release checks: display scaling, fonts, title bar/Mica, tray, installer, signing/SmartScreen, proxy, sign-in. |

### Integrations

| Choice | Status | Notes |
|---|---|---|
| **IMAP + SMTP, profile-based config** | Decided | `mail-accounts.json` with named profiles (corporate server, Gmail test account). Corporate login is plain username + password over TLS (no custom root certificate). Passwords in the OS credential store, never in the file. |
| `imapclient` | In use | IMAP with IDLE, on a dedicated worker thread. Replaced `aioimaplib` because it's simpler and mature. Works against Gmail; confirm against the corporate server. |
| Python `email` package | Decided | Parses raw messages (MIME, attachments, headers). |
| `smtplib` (standard library) | In use | SMTP sending. Replaced `aiosmtplib`, because handlers already run on worker threads. |
| `libpff-python` (`pypff`) | In use | Reads Outlook PST archives in a separate process. Works on a real 2,178-message archive on macOS. Confirm with a multi-GB archive and on Windows. |
| SQLite FTS5 | Decided | Full-text search over all mail history (~10K+ messages). |
| Rule engine (`rules.json`) | Decided | Our own: built-in header rules + user rules run before the agent. |
| Model provider interface | Decided | One interface for all models, with a capability flag for tool calling and a JSON-in-prompt fallback for models without it. |
| Internal company LLM API | Decided, not built | Assumed to be a LiteLLM server, so it's an OpenAI-compatible address and key, with its model list read from the server. Available now without tool calling (uses the fallback); a version with tool calling is coming. |
| **ChatGPT subscription** | In use for testing | Device-code sign-in with no API key, the method Hermes Agent and OpenClaw use. Models come from the account's own list. Tokens stay in the OS credential store. Requests carry NexusAI's own name. It uses Codex's sign-in client because OpenAI hasn't issued one for NexusAI, so OpenAI could change or stop this. Test data only: it's a personal subscription, so corporate mail needs a company-approved model. |
| Claude subscription | Rejected | Anthropic's terms don't allow Free, Pro or Max sign-ins in other tools. Claude would need an API key. |
| Gemini via Google Cloud (enterprise auth) | Decided | Native tool calling. Approved for mail content. |
| **ONNX Runtime** (`onnxruntime`) | Decided | Local models for text embeddings, OCR and image description. CPU everywhere; DirectML (Windows) / CoreML (macOS) when available. Specific models to be chosen. |
| MCP (Model Context Protocol) | Decided | Connectors are MCP servers with tools, skills and resources; built-in ones such as Mail run in-process, others connect by URL or as separate processes. |
| Outlook COM automation | Considered | Optional fallback for classic Outlook only; not needed while IMAP works. |
| Microsoft Graph + MSAL | Considered | Not needed while IMAP is available. |
| Node.js backend | Considered | Previous plan. Replaced by Python so the agent can use LangChain's Python tools directly. |

### Design resources

We adapt these to speed up the build. Everything copied is rebuilt on our theme tokens, and its license notice is kept in `THIRD_PARTY_NOTICES`.

| Resource | What it is | License / cost | How we use it |
|---|---|---|---|
| [Beautiful UI](https://www.beautifului.dev/) | ~21 primitives for AI interfaces: thinking traces, streaming text, approval card, prompt bar, task rows, diff/records tables, agent screen | Free, MIT (© 2026 Shane Levine) | Main source for agent screens: approval, thinking, streaming, chat, prompt bar, tables. |
| [unslop](https://github.com/heydamir/unslop) | Claude Code / Codex skill that audits "AI-looking" UI and redesigns it in passes | Free, CC BY 4.0, commercial use OK with credit to Damir Sokolovsky + repo link | Dev tool: sets the design direction, then `/unslop` runs on every screen. Installed at the start of UI work. Paid image generation and videos stay off unless requested. |
| [AICSS](https://www.aicss.dev/) | Copy-paste blocks for agent UIs: reasoning, tool states, citations, tables, approval cards, agent input (React/Vue/Svelte) | Free components: MIT. **Pro** components: paid ($89 one-time per single developer; Enterprise for teams, price on request) | Free components may be adapted. We do not copy or recreate Pro components unless the company buys an Enterprise license. |
| [Amicro](https://amicro.dev/) | 170+ React micro-interactions (buttons, cards, loaders, text effects), React + Tailwind + Motion | Free, MIT | Micro-interactions, adapted to theme motion tokens; we already use Tailwind and Framer Motion. Recheck the license on first use. |

## Windows corporate checklist

- [ ] ChatGPT tokens fit Windows Credential Manager, which limits each secret's size; split them if not

- [ ] Code-signing certificate (company cert or IT approval); unsigned `.exe` is blocked by SmartScreen/AppLocker
- [ ] Per-user installer works without admin rights
- [ ] Node-side network calls respect the corporate proxy (Chromium requests already do)
- [ ] Use `path.join` and `app.getPath(...)`; no hard-coded `/` or case-sensitive file names
- [ ] Verify at 125% and 150% display scaling

## Build order

The MVP build stages and feature targets are in [`FEATURES.md`](FEATURES.md).

## Change log

| Date | Change |
|---|---|
| 2026-11-01 | Mail stage built: `imapclient` and `smtplib` replace the async clients, `nh3` sanitizes mail, `pypdf` and the Office libraries read attachments. Synced and sent with the real Gmail test account. |
| 2026-11-01 | ChatGPT subscription connected by device-code sign-in, with models chosen from the account's list. Internal API assumed to be LiteLLM. Web app gets built fully before Windows and corporate laptop testing. |
| 2026-11-01 | Design direction approved: warm paper surfaces and Instrument Sans. Fonts are chosen per theme from a catalog. |
| 2026-11-01 | Initial stack: Electron shell over the existing Next.js app; Playwright + Windows CI/VM for testing; v9 chosen as design reference. |
| 2026-11-01 | Added design resources: Beautiful UI, unslop, AICSS (free tier only), Amicro. |
| 2026-11-01 | Repo cleanup: old prototype, docs, designs and hallmark skill moved to `archive/2026-11-01/`. Fresh Next.js shell with v9 colors and fonts. |
| 2026-11-01 | Mail via IMAP/SMTP profiles (corporate + Gmail test), PST import, rule filters before the agent, user-selectable models (internal API, Gemini). Graph moved to Considered. |
| 2026-11-01 | Agent built on LangGraph.js + LangChain.js, behind our own policy layer. |
| 2026-11-01 | **Backend moved to Python with `uv`, with LangChain + LangGraph for agents. Web app first, Electron later.** Repo cleaned up; docs moved to `docs/`. |
| 2026-11-01 | Component plan written: theme files, no hardcoded values, adapted component sources, unslop on every screen. |
| 2026-11-01 | Agent channel and PST import moved into the MVP. |
| 2026-11-01 | Architecture set: separate processes, event bus, modular contracts, one-door gateways. See `ARCHITECTURE.md`. |
| 2026-11-01 | Feature list regrouped and consolidated, with MVP, Next and Later targets set. |
| 2026-11-01 | Modules renamed connectors; any MCP server can be added in Settings. Panels added. |
| 2026-11-01 | Added shared work board and agent channel; defaults reduced to Live mail agent, Daily prep and Time check. |
| 2026-11-01 | One agent invoked from many places, with system context injected only in the system prompt. Meeting transcription with a local ONNX speech model. |
| 2026-11-01 | Threads become the main unit for the Mail agent, with summaries generated only on request and then stored. Flags from the internal LLM show an error message. |
| 2026-11-01 | Added sensitive data mapper for all model calls; SQLite must be an encrypting build. |
| 2026-11-01 | Consolidated feature list; one Home per user; autonomy levels become presets for tool permissions. |
| 2026-11-01 | Layered prompts and multi-level memory stored as markdown in Home; event-triggered Mail agent. |
| 2026-11-01 | App data moves from `userData` to a user-selected NexusAI Home with `system/`, `memory/` and `scratch/` folders; passwords stay in the OS credential store. |
