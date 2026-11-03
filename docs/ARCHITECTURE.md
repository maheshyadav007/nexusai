# NexusAI Architecture

How NexusAI is built so it stays fast, modular, easy to debug and hard to break. Features are in [`FEATURES.md`](FEATURES.md), technology choices in [`TECH_STACK.md`](TECH_STACK.md). Numbers below are targets, not measurements.

## 1. The rules

Every design and code review checks these.

1. **Nothing polls inside the app.** When something changes, an event is emitted and whoever cares reacts.
2. **The UI never does the work.** It displays state and sends requests. Mail, the database, agents and AI models run in other processes, so the UI can't freeze.
3. **Modules talk only through contracts.** Commands, queries and events are the only way in or out of a module, and a build check rejects anything else.
4. **One door each for model calls, tool calls and database writes.** Safety, limits and logging live at the door, so no feature can skip them.
5. **Every change is traceable.** A trace ID follows the work from its first event to its last.
6. **A crash loses nothing.** Work is saved in steps, and a crashed process restarts and resumes.
7. **Check data at every boundary.** Anything crossing between processes, or from outside the app, is validated against a schema.
8. **Status is an explicit state machine,** with allowed moves between named states, never a collection of true/false flags.
9. **Every bug fix adds a test** that would have caught it.
10. **Dependency versions are pinned exactly.** No `latest`.

## 2. Processes

The app is built **web first**: a Next.js UI talking to a local Python backend. Electron comes later as a wrapper, with no change to the backend or screens.

```text
┌───────────────┐  HTTP: commands and queries   ┌─────────────────────────────────────┐
│ UI (browser,  │──────────────────────────────▶│ Core process (Python, FastAPI)      │
│ later Electron│◀──────────────────────────────│ Event bus · Database (only writer)  │
│ window)       │  SSE: events pushed live      │ Scheduler · Modules: mail, rules,   │
└───────────────┘                               │ threads, search, tasks, panels ...  │
                                                └───────┬─────────────────┬───────────┘
                                                        ▼                 ▼
                                         ┌─────────────────────┐ ┌─────────────────────┐
                                         │ Agent host (Python) │ │ Heavy jobs (Python) │
                                         │ LangChain/LangGraph │ │ PST import, text    │
                                         │ sessions, gateways  │ │ extraction, ONNX    │
                                         └─────────────────────┘ └─────────────────────┘
```

The backend keeps running when the browser tab is closed, so mail and agents continue.

| Process | If it crashes |
|---|---|
| UI | Reloads and catches up from the event log |
| Core | Restarted by its supervisor; the UI shows "Reconnecting" briefly; events resume from the last saved position |
| Agent host | Restarted; sessions resume from their last checkpoint |
| Heavy jobs | Restarted; the job continues from its last saved batch |

**Local server security:** the Command tool makes the backend powerful, and any website a user visits could try to call a local port. So the backend listens only on `127.0.0.1`, rejects requests whose `Host` or `Origin` isn't the app's own, and requires a per-install token before any feature that touches mail or tools.

**Electron later:** Electron adds the window, tray, pop-up and start at login, and launches the Python backend as a sidecar using a bundled standalone Python rather than a frozen executable, which corporate antivirus tends to flag. Test this on a real corporate laptop early, because it's the main risk of a Python backend.

## 3. Three ways to communicate

| Type | Meaning | Answer | Example |
|---|---|---|---|
| **Command** | "Do this" | Accepted or an error; the result arrives as events | `mail.send`, `session.start` |
| **Query** | "Tell me this" | Data; changes nothing | `threads.list`, `search.run` |
| **Event** | "This happened" | None; anyone can listen | `mail.received`, `session.waitingForApproval` |

All three are defined once as Pydantic models in `backend/src/nexusai/contracts/`. TypeScript types for the UI are generated from them, so a mismatch fails the build.

## 4. Event bus

The bus lives in Core. Modules subscribe in-process, the UI over SSE, and the Agent host over a local connection. Publishers don't know who is listening, so adding a new listener never changes existing code.

```ts
interface AppEvent<T> {  // generated from the Pydantic contract
  id: string;        // unique, used to ignore duplicates
  seq: number;       // position in the log, used to catch up
  type: string;      // "mail.received"
  version: number;   // payload format version
  time: string;
  source: string;    // module that emitted it
  traceId: string;   // shared by all work from one starting point
  causeId?: string;  // the event that led to this one
  payload: T;        // IDs and short facts, not mail bodies
}
```

| Kind | Used for | Handling |
|---|---|---|
| **Durable** | Facts that matter: mail received, task created, approval given | Saved in the same database transaction as the change itself, so a change can never exist without its event, or the reverse |
| **Live** | Fast and disposable: streamed text, progress | Not saved; merged to at most about 10 updates per second per item |

**How it stays reliable:**
- **Catching up:** each durable listener saves its last `seq`. After a crash or UI reload, it asks for everything since then.
- **Duplicates are harmless:** handlers ignore an event ID they've already processed.
- **Failures are isolated:** a failing listener doesn't affect others. It retries with increasing delays, then moves to a failed list shown in Logs.
- **No private data:** payloads hold IDs, so the event log and logs stay free of mail content. A listener that needs the content queries for it.
- **Schema checked:** every event is validated when published, and old versions remain readable.

**Avoiding loops:** to reduce event storms, a chain that exceeds a set depth from its `causeId` stops and logs an error.

**Agent channel:** agent messages use this same bus as the backbone for agents working together, with the permission rules from [`FEATURES.md`](FEATURES.md) (`BUS-4`, `BUS-5`).

### What replaces polling

| Instead of checking repeatedly for | We react to |
|---|---|
| New mail | IMAP IDLE, emitting `mail.received`. POP3 can't announce mail, so it's a check every minute |
| Reminders and deadlines | One timer set for the next due time, reset whenever the schedule changes |
| Files edited outside the app | File system watcher |
| Laptop waking or network returning | Electron `powerMonitor` and network events |
| UI needing fresh data | Events, which mark that screen's data out of date |

**The only exceptions** are outside systems with no way to notify us, such as a mail server without IDLE or a connector with no events. That polling stays hidden inside the connector, which still emits normal events, so nothing else knows the difference.

### Example: a new email arrives

```text
mail.received          Mail connector saves the message
  ├─ threads           groups it → thread.updated
  ├─ search            indexes it
  ├─ rules             checks fixed rules → mail.ruleMatched, or mail.needsTriage
  │    └─ agent host   Mail agent runs, in a group if there's a burst → mail.triaged
  │         ├─ work board      records deadlines and status
  │         ├─ notifications   pop-up if urgent
  │         └─ UI              inbox updates live
  └─ UI                inbox shows the new mail immediately
```

Every step shares one `traceId`, so the whole journey appears in one view in Logs.

### Starting an agent

A typed message, an event and the clock all reach `SessionRuntime.dispatch` as the same kind of start, and each emits `agent.triggered`. Time is an event too: the scheduler emits `schedule.due`. A record in `trigger_runs` means a replayed event can't start a run twice.

Each agent has one chat, and each schedule has its own. What the chat shows comes from `agent_parts` and is never shortened. What the model is sent is decided per run in `modules/agent/context.py`:

| Way of keeping context | Saved history | Used for |
|---|---|---|
| Trim, saved | Shortened | Events and schedules, by default |
| Trim, view only | Unchanged | Typed messages, by default |
| Auto compact | Older part replaced by a summary | Off by default |
| Compact now | Older part replaced by a summary | On request |
| Clearing old tool results | Unchanged | Always, at a high limit |

The defaults are in `defaults.toml`, Settings can change them, and a schedule can have its own. A trigger's data, such as an email's body, goes beside its message for that run only. It's never saved in the history, and it never sits with the instructions.

## 5. Modules and interfaces

A module owns one area. Its data and code are private, and others reach it only through its contract. Replacing a module's internals never affects another module.

```python
reminders = Module(name="reminders")

@reminders.command("reminders.create")
def create_reminder(cmd: CreateReminder, ctx: Context) -> Reminder: ...

@reminders.query("reminders.list")
def list_reminders(q: ListReminders, ctx: Context) -> list[Reminder]: ...

@reminders.on("task.completed")
def close_linked_reminders(event: TaskCompleted, ctx: Context) -> None: ...
```

**Interfaces where parts are swappable:**

```python
class Connector(Protocol):      # Mail, PST, Calendar, any MCP server
    id: str
    def tools(self) -> list[ToolDefinition]: ...
    def skills(self) -> list[Skill]: ...
    def resources(self) -> list[ResourceDefinition]: ...
    def events(self) -> list[EventDefinition]: ...
    async def start(self, ctx: ConnectorContext) -> None: ...
    async def stop(self) -> None: ...

class ModelProvider(Protocol):  # Internal API, Gemini, local
    id: str
    capabilities: ModelCapabilities  # tool calling, streaming
    def complete(self, request: ModelRequest) -> AsyncIterator[ModelChunk]: ...

class Tool(Protocol):           # Read, Edit, Command, connector tools
    name: str
    risk: Literal["read", "write", "send", "command"]
    input_model: type[BaseModel]
    async def run(self, input: BaseModel, ctx: ToolContext) -> BaseModel: ...
```

**Enforced:** `import-linter` fails the build if a Python module imports another module's internals. The UI can only reach the backend through its typed client.

## 6. One door for each risky thing

```text
Model call:  prompt builder → mask sensitive data → check usage limit → provider
                                                                          │
             stored and logged ← restore real values ←────── model reply ◀┘

Tool call:   restore real values → check permissions and untrusted rule → approval if needed
                                                                          │
             mask result for the model ← log ←──────────────────── run ◀──┘

DB write:    module → repository → transaction (data change + its event)
```

LangChain and LangGraph handle agent flow, but it only reaches models and tools through these doors. This means the data guard, permissions and logging can't be skipped by any feature, now or later.

## 7. Data

- **SQLite in WAL mode:** readers don't block the writer.
- **One writer for each file:** only Core writes, through a single connection per database. Other processes send commands, and Heavy jobs send results in batches. This removes a whole class of locking bugs.
- **Search indexes are separate files:** `system/index/mail.db` and `system/index/document.db` hold vectors and a manifest of exactly what built them. They're encrypted with the same key, can be rebuilt from mail and documents, and stay out of backups. A change and its event are still saved together, because they're never in an index file.
- **Migrations:** numbered and forward-only, run automatically after a backup. Tested against a copy of an older database.
- **Tables per module:** a module doesn't read another's tables. Panels are the planned exception, going through a read-only query layer.
- **Large content:** attachments live on disk, stored by hash, with only references in the database.

## 8. State machines

Long-running things have named states and allowed moves, stored in the database, and each move emits an event.

```text
Session:     queued → running ⇄ waitingForApproval → done
                        ├──▶ paused ──▶ running
                        └──▶ failed
Mail sync:   idle → connecting → syncing → live → (disconnected → connecting)
             any state → paused (by the person, and kept across restarts) → connecting
             older mail: coming → finished (budget used, Stop, or all here) → coming (Get more)
Approval:    pending → approved | denied | expired
```

An illegal move is logged as an error and rejected, rather than leaving something half-done.

## 9. Frontend

- **Next.js:** served locally for the web build, then a static export that Electron loads from local files.
- **Server data:** TanStack Query holds it, and events mark it out of date, so the UI has one source of truth and never polls.
- **UI-only state:** Zustand, for things like open panels and selections.
- **Long lists:** virtualized, so 100,000 emails render as smoothly as 100.
- **Feature folders:** each screen uses only the shared typed client, never `fetch` or Electron directly.
- **Error boundaries per panel:** one failing panel shows an error and doesn't take down the page.
- **Theme tokens:** colors are CSS variables, so themes switch instantly.

## 10. Speed targets

| Measure | Target |
|---|---|
| Click to visible response | Under 100 ms |
| Opening inbox or a thread | Under 200 ms |
| Keyword search, 100,000 emails | Under 300 ms |
| Launch to usable Today | Under 3 s |
| New email to inbox, before any model call | Under 1 s |
| Blocking work on the UI thread | Never over 50 ms |

Measured in automated tests, using a generated mailbox of 100,000 messages. A regression fails the build.

**How we hit them:** indexed queries with paging, and lazy loading of bodies and attachments. Screens load only their own code, and heavy work stays in other processes.

## 11. Debugging

- **Trace view in Logs:** enter any email, session or error, and see everything that happened across all processes, in order, with timing.
- **Event inspector (`ARC-5`):** a live view of events and their listeners, with failed ones listed.
- **Structured logs:** JSON via `structlog`, always including process, module and `traceId`, with secrets removed centrally.
- **Coded errors:** each error has a code, a plain message for the user, and technical detail for logs.
- **Support report:** one click bundles logs, versions and diagnostics, with secrets and mail content removed.
- **Replay:** model replies can be recorded and replayed, so an agent problem can be reproduced without calling the model.

## 12. Testing

| Level | What it covers | Tool |
|---|---|---|
| Unit | Rules, thread grouping, data guard masking and restoring, state machines | pytest |
| Module | One module with a real temporary database and test bus | pytest |
| Contract | Every connector and provider passes the same interface test suite | pytest |
| Agent | Scripted flows with a fake model; no tokens spent | pytest + recorded replies |
| Safety | Permissions, untrusted content rule, and no raw sensitive value reaching a provider | pytest |
| UI | Components, theme validation and the no-hardcoding check | Vitest + check scripts |
| Full app | Onboarding, new mail to triage to approval | Playwright |
| Speed | The targets above | Playwright + generated mailbox |

## 13. Folder layout

```text
docs/                 plans, design reference
frontend/
  app/                Next.js pages
  ui/                 theme, components, feature screens, typed client
backend/
  src/nexusai/
    contracts/        commands, queries, events and interfaces
    kernel/           event bus, database, scheduler, logging, config
    modules/          mail store, threads, rules, search, tasks, reminders, panels, work board ...
    connectors/       mail, PST, later calendar, files, MCP client
    agent/            LangChain/LangGraph runtime, prompt builder, model gateway, data guard, tools, policy
    jobs/             heavy job handlers
    api/              FastAPI routes and SSE
  tests/
archive/              old work, reference only
```

Electron later adds a `desktop/` folder.

## 14. Build order for the foundation

Build this before any feature, because everything else depends on it:

1. Backend skeleton with config, logging, local server security
2. Contracts, event bus, database, migrations
3. Typed UI client, with query and event handling
4. Theme system and build checks (no hardcoding, module boundaries, type checks, tests)
5. One thin feature through every layer as a proof: **Settings → change theme**, with the event inspector showing it

After that, features follow the stages in [`FEATURES.md`](FEATURES.md).

## The Mail agent's judgement

What it knows, strongest first, and how far each is trusted. `modules/agent/knowledge.py` builds this for a real run and for the "What it knows" page, so the page can't drift from what the model is sent.

| Layer | Comes from | Trust |
|---|---|---|
| About the person, Personalized prompts | Profile and prompt files | The person's own words, and they always win |
| What you corrected | `mail_feedback`, from their own changes. An agent's changes don't count | Theirs |
| What the mailbox shows, and the facts with each email | Counted by `modules/agent/signals.py` with no model | Reliable |
| Memory: confirmed | `memory/user/` | Theirs |
| Memory: learned | `memory/agents/mail/learned.md`, each note marked with the mail it came from | Untrusted hints, because anyone can send mail |
| The email | The server | Untrusted, and the weakest evidence of its own importance |

- **Who has the next move** is status, and what they'd do is `next_action`. Interrupting is `notify`, decided apart from importance. Questions stop at three open.
- **Without any model:** sending takes a conversation off their plate at once, a reply moves it back, and a follow-up date that passes tells them once.
- **Automated mail** skips the model unless its subject could cost them something, or it's in a conversation they wrote in.
- **A broadcast** (more than 10 recipients) reaches the model as a count, and `read_recipients` searches the list if it matters.
- **Recommendations** name real senders only, show the app's own counts, and do nothing until the person agrees. Quiet groups only archive what's read and over a month old. Nothing is ever deleted.
- **Prompts are checked** with `make eval-mail`, which runs made-up emails through the real model. Tests use a fake model and can't judge wording.

## Search

Mail search runs in three steps. The search page, the palette, folder filters and the agent's tools all share it.

1. **Understand the words.** `store.with_operators` turns `from:`, `to:`, `subject:`, `has:attachment`, `is:unread`, `in:`, `before:`, `after:` and `category:` into filters, so typing them works everywhere. Common words are ignored unless they're all that was typed.
2. **Find by words.** FTS5 looks for every word, with a subject match worth most. If that finds nothing, a likely typo is corrected from words the mailbox really contains, and the result says so. If there's less than a page, mail with only some of the words follows.
3. **Add meaning, then rank.** Local embeddings join by rank fusion, weighted below words. Some models score unrelated text nearly as high as a match, so a meaning match counts only if it stands out from that query's usual score. Conversations the person wrote in rank higher, and promotions and low importance rank lower.

- **Documents** rank a match in the name above one in the text, and that above meaning. Older attachments are read in the background, on the computer, with no model and no tokens.
- **Agents** get `search_mail` with filters and dates, labelled when a result only matches by meaning, and `semantic_search` for topics, which shows its closest matches as possibly unrelated when nothing stands out.

## The morning brief

A daily schedule writes the brief from what's on the person's plate, and it shows first on Today. Reactions are kept per brief in `brief_feedback`. Their ratings and own words reach the next run as the trusted layer "How they want the brief", while what each rated brief said goes in the task as untrusted, because it came from reading mail.

Prompts can only change from a session that read mail if the person approves the exact words, and that approval can't extend to the rest of the session.

