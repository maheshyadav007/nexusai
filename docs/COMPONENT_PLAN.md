# NexusAI Component Plan

The parts to build for the MVP, how they fit together, and the order to build them. Features and IDs are in [`FEATURES.md`](FEATURES.md), system design in [`ARCHITECTURE.md`](ARCHITECTURE.md), technology in [`TECH_STACK.md`](TECH_STACK.md). Visual reference: [`design/NexusAI v9.dc.html`](design/NexusAI%20v9.dc.html).

## 1. Nothing is hardcoded

| Kind of value | Lives in | Never in |
|---|---|---|
| Colors, spacing, radius, shadows, type sizes, fonts, motion | Theme files (section 2) | Components, inline styles, Tailwind arbitrary values such as `text-[13px]` |
| User-facing text | `frontend/ui/strings/en.json` | Components |
| Icons | `frontend/ui/icons/` map, by purpose | Direct imports in features |
| Limits, timeouts, batch sizes, default schedules and session counts | `backend/src/nexusai/kernel/defaults.toml`, overridable by Settings | Module code |
| Model names, API addresses, mail servers | User configuration in `system/` | Code |
| Data guard rules, including `samsung` | `backend/src/nexusai/agent/guard/default-rules.json` copied to Home, editable | Code |
| Built-in prompts | `backend/src/nexusai/agent/prompts/*.md` | Code strings |
| Keyboard shortcuts | `frontend/ui/shortcuts/default-shortcuts.json` | Components |
| Names, counts and other content | Real data through queries; demo data only in `frontend/ui/gallery/fixtures/` | Screens |

**Enforced by build checks:** a script (`frontend/scripts/check-no-hardcode.mjs`) rejects hex or `rgb()` colors, Tailwind arbitrary values, inline `style` colors and bare text in JSX outside the allowed folders. So the rule holds even when code is written fast.

## 2. Theme system

Components use **semantic tokens** that say what a value is for, such as `surface-page` or `text-muted`. A theme file gives each token its value. Components never know which theme is active.

```text
frontend/ui/theme/
  schema.ts                 every token, with validation
  themes/
    nexus-light.json        from v9
    nexus-dark.json         to be designed
  generate.ts               turns theme JSON into CSS variables at build time
  ThemeProvider.tsx         applies data-theme, accent, density and text size
tailwind.config.ts          maps Tailwind names to CSS variables only, no values
```

```json
{
  "id": "nexus-light",
  "mode": "light",
  "color": {
    "surface": { "page": "#F8EAE2", "raised": "...", "sunken": "...", "inverse": "#1B1815" },
    "text": { "primary": "#191714", "secondary": "#4A423A", "muted": "#6E645A" },
    "accent": { "default": "#A8441F", "hover": "#8E3717", "onAccent": "#FCF3EE" },
    "status": { "success": "#3B5C33", "warning": "#7A5410", "danger": "#A83226" },
    "agent": { "running": "...", "waiting": "...", "done": "...", "failed": "..." },
    "border": { "subtle": "...", "strong": "..." }
  },
  "type": { "family": { "sans": "...", "serif": "...", "mono": "..." }, "size": { "xs": "11px", "sm": "12px", "md": "13px", "lg": "15px", "xl": "19px", "display": "..." } },
  "space": { "1": "4px", "2": "8px", "3": "12px", "4": "16px", "5": "24px", "6": "32px" },
  "radius": { "sm": "6px", "md": "9px", "lg": "14px", "full": "999px" },
  "shadow": { "raised": "...", "overlay": "..." },
  "motion": { "fast": "120ms", "normal": "200ms", "easing": "..." }
}
```

- **Switching is instant:** the app changes one attribute, and CSS variables do the rest, with no re-render of screens.
- **No flash at startup:** the saved theme is applied before first paint.
- **Accent, density and text size (`SET-1`):** these override individual variables.
- **Native window parts:** Mica, vibrancy and title bar colors will come from the same theme file when Electron is added.
- **Emails keep their own look:** HTML mail renders in a sandbox (`PRC-7`). Theme tokens cover the surrounding frame only.
- **Validated:** the build fails if a theme is missing a token, or if text and background pairs fall below contrast targets.

### Corrections to v9 for readability

Measured against the v9 page color (`#F8EAE2`), with 4.5:1 as the usual minimum for small text:

| v9 color | Contrast | Plan |
|---|---|---|
| `#8A7F73` muted text, the most used color in v9 | 3.33:1 | Use `#6E645A` (4.91:1) for text; keep the original for icons and dividers |
| `#A79B8D` faint text | 2.31:1 | Decoration only, not for reading |
| `#C0532E` bright accent | 3.95:1 | Large text, fills and icons only |
| `#4E7A43` green, `#9A6A12` amber | 4.26:1, 4.02:1 | Use `#3B5C33` (6.46:1) and `#7A5410` (5.76:1) for text |

v9 also uses text as small as 8.5–10px, which is hard to read on corporate screens at 125–150% scaling. The minimum becomes **11px**, and the layout stays dense through spacing and hierarchy.

## 3. Where components come from

Copying is allowed where licenses permit, so we move faster. Everything copied is then rebuilt on our tokens.

| Source | Use for | License and limits |
|---|---|---|
| **Radix UI primitives** | Behaviour and accessibility of Dialog, Menu, Popover, Tabs, Tooltip, Select, Switch | MIT. Unstyled, so all looks come from our tokens |
| **Beautiful UI** | Main source for agent screens. 21 primitives, all listed below | MIT. Keep notice. Copy-paste; stack not stated, so check each on import |
| **AICSS free components** | Thinking and reasoning, inline citations, code and data blocks | MIT, public packages only. Snippets are self-contained CSS, so rewrite to tokens |
| **Amicro** | Micro-interactions | MIT per earlier review; page wasn't reachable this time, so recheck on first use |
| **Our own code** | Mail, threads, panels, data guard screens, and anything specific to NexusAI | |

**AICSS Pro is not used.** Audio Waves, Image Processing, To-do List, AI Agent Input and Approval Card appear to be Pro. We don't copy or recreate them, and Beautiful UI already provides an Approval Card, Task Rows and Prompt Bar. Confirm the exact free list from the AICSS public repo when importing.

**Import checklist**, run for each copied component:
1. Check the license, and record it in `THIRD_PARTY_NOTICES`.
2. Replace all colors, sizes and motion values with tokens, and text with strings.
3. Check keyboard use, focus, light and dark themes, and reduced motion.
4. Add its states to the gallery, and remove unused dependencies.

### Mapping to our components

| Our component | Start from | Used in |
|---|---|---|
| `ApprovalCard` | Beautiful UI Approval Card | Approval queue, user channel, sessions |
| `ThinkingTrace` | Beautiful UI Thinking; AICSS Thinking + Reasoning | Sessions, user channel |
| `StreamingText` | Beautiful UI Streaming Text; AICSS Streaming Text | Sessions, thread summary, drafts |
| `LoadingState` | Beautiful UI Loading State | Everywhere |
| `ToolCallChips` | Beautiful UI Tool Chips | Sessions, Logs |
| `TaskRows` | Beautiful UI Task Rows | Tasks, Background, Today |
| `ChatThread` | Beautiful UI Chat | Sessions, Setup interview |
| `PromptBar` | Beautiful UI Prompt Bar | Today, sessions, "Ask agent" |
| `SuggestionCard` | Beautiful UI Recommendation Card | User channel |
| `ContextChips` | Beautiful UI Context Cards | Prompt bar, "Ask agent" (`AGN-10`) |
| `DiffView` | Beautiful UI Diff Table; AICSS File Diff | Approval cards, prompts |
| `RecordsTable`, `FilterTable` | Beautiful UI Records Table and Filter Table | Panels, Documents, Logs |
| `NavSidebar` | Beautiful UI Sidebar Nav, with our drag behaviour | App shell |
| `SearchBox` | Beautiful UI Search | Search, command bar later |
| `TraceFlow` | Beautiful UI Flowchart | Logs trace view |
| `InsightCard` | Beautiful UI Insight Cards | Today, Daily prep |
| `CodeBlock` | Beautiful UI Code Block; AICSS Code Block | Sessions, command output |
| `SelectionActions` | Beautiful UI Selection Actions | "Ask agent" on selected text |
| `AgentScreen` | Beautiful UI Agent Screen | Session view |
| `Citations` | AICSS Inline Citations | Answers with sources (`AGT-4`) |
| `MessageActions` | AICSS Message Actions | Agent replies and drafts |

## 4. Reaching top-level UI with unslop

[unslop](https://github.com/heydamir/unslop) is a Claude Code skill (CC BY 4.0, credit Damir Sokolovsky) that audits an interface for signs of AI-made design, proposes a direction, then fixes in passes: spacing, color, icons, copy, type, layout, details, visuals and motion. It isn't installed yet, and is added to `.claude/skills/` when UI work begins. We review its files before first use.

**Workflow:**

1. **Set the direction once.** Run unslop's Audit and Direction on v9, and save the result in `ui/DESIGN_DIRECTION.md`. All screens follow it, so they feel like one product.
2. **Build the screen** with tokens and components above.
3. **Run `/unslop` on each finished screen,** with its audit list saved.
4. **Apply fixes at the right level:** to theme files, then shared components, and only then the screen. Fixes never become hardcoded values.
5. **Pass the quality bar** below, and save visual snapshots.

**Guardrails:**
- Only gallery demo data appears in anything unslop sees, so real mail never reaches screenshots.
- Paid image generation and story videos are off unless you ask for them.
- Playwright is already planned, so its live snapshots are available.

**Quality bar for every screen:**

| Check | Standard |
|---|---|
| States | Loading, empty, error, offline and full, all designed |
| Screens | 1366px and 1536px wide, at 100%, 125% and 150% scaling |
| Themes | Light and dark, with contrast targets met |
| Keyboard | All actions reachable, with visible focus and an alternative to every drag (`APP-12`) |
| Motion | Purposeful and short, and respects reduced motion |
| Copy | Plain and specific, with errors saying what to do next |
| Speed | Meets the targets in `ARCHITECTURE.md` |
| Audit | No open unslop findings |

**Gallery:** a development-only `/gallery` route shows every component in every state and theme. It's where unslop runs and where visual tests compare snapshots.

## 5. UI components

```text
ui/
  theme/  strings/  icons/  shortcuts/  gallery/
  primitives/     no product knowledge
  agent/          agent interaction components
  shell/          app frame
  features/       one folder per screen
  client/         typed commands, queries and event subscriptions
```

Dependency direction runs one way, and the build enforces it: `features → shell, agent → primitives → theme`.

### Primitives

| Group | Components |
|---|---|
| Actions | `Button`, `IconButton`, `Link`, `Kbd` |
| Forms | `Input`, `Textarea`, `Select`, `Checkbox`, `Radio`, `Switch`, `Segmented`, `Slider`, `Field`, `FileDrop`, `FolderPicker` |
| Overlays | `Dialog`, `Drawer`, `Popover`, `Menu`, `Tooltip`, `Toast` |
| Display | `Badge`, `Avatar`, `StatusDot`, `Card`, `Divider`, `Tabs`, `Accordion`, `Stepper`, `Progress` |
| States | `Skeleton`, `EmptyState`, `ErrorState`, `OfflineNotice`, `ErrorBoundary` |
| Layout | `Stack`, `Grid`, `ScrollArea`, `ResizeHandle`, `SplitPane`, `VirtualList`, `Sortable` |

### Shell

| Component | What it does | Features |
|---|---|---|
| `AppShell` | Window frame, title bar area, layout and reconnect banner | `APP-1`, `ARC-1` |
| `NavSidebar`, `SidebarEditor` | Navigation with counts; drag, nest, hide and reset | `NAV-1`, `NAV-4` |
| `TopBar`, `ApprovalQueue` | All pending approvals in one place | `TOL-3` |
| `NotificationCenter` | History, unread count, filters | `NTF-5` |
| `ActivityIsland` | v9 collapsible status chip: running work and next item | `JOB-1` |
| `AskAgentAction` | "Ask agent" with attached context, on any item | `AGN-10` |
| `MailPopup` | Browser notification on the web; separate small window in Electron | `NTF-1` |

### Screens

| Screen | Main components | Reads | Reacts to | Features |
|---|---|---|---|---|
| **Landing** | `Hero`, `PrivacyPromise`, `GetStarted` | App state | | `ONB-1` |
| **Onboarding** | `OnboardingFlow`; steps: `HomeStep`, `ThemeStep`, `ProfileStep`, `MailStep`, `ModelStep`, `InterviewStep`, `PrioritiesStep`, `PstStep`, `PermissionsStep`; then `EnterApp` transition | `onboarding.state` | `onboarding.stepChanged`, `mail.connectionTested` | `ONB-2`, `ONB-4`, `HOM-1`, `PMT-3`, `PMT-10` |
| **Home not found** | `HomeRecovery` | `home.status` | | `HOM-4` |
| **Today** | `DailyBrief`, `NeedsYou`, `WaitingList`, `AutomatedGroup`, `UserChannel`, `PromptBar` | `today.view`, `channel.list` | `mail.triaged`, `channel.posted`, `prep.finished` | `NTF-3`, `CHN-1`, `CHN-3`, `CHN-5`, `CHN-7` |
| **Inbox** | `MailList`, `CategoryTabs`, `MailRow`, `WhyHere`, `DraftsList` | `threads.list` | `mail.received`, `thread.updated` | `NAV-2`, `ACC-6`, `ACC-8`, `PRC-6`, `THR-4`, `THR-5` |
| **Thread** | `ThreadView`, `MessageCard`, `SafeMailFrame`, `SummaryBlock`, `AttachmentList`, `ReplyComposer`, `SendCheckNotice` | `thread.get` | `thread.updated`, `summary.ready` | `THR-2`, `THR-3`, `THR-9`, `PRC-7`, `PRC-8`, `ATT-1`, `AGT-3`, `TOL-9` |
| **Archive (PST)** | `PstImportCard`, plus thread and inbox components | `pst.imports` | `pst.progress` | `PST-1` |
| **Search** | `SearchBox`, `SearchFilters`, `SearchResults` | `search.run` | | `SRC-1` |
| **Documents** | `DocumentLibrary`, `FolderTree`, `DocumentPreview`, `UploadZone` | `documents.list` | `document.indexed` | `DOC-1`, `DOC-2`, `DOC-4`, `ATT-2` |
| **Panels** | `PanelBoard`, `Panel`, `PanelBuilder`, `FilterEditor`, `PanelResults` | `panels.board`, `panels.results` | `panels.changed`, source data events | `PNL-1`, `PNL-3`, `PNL-5` |
| **Sessions** | `SessionList`, `AgentScreen`, `ChatThread`, `ThinkingTrace`, `ToolCallChips`, `CommandOutput`, `DiffView`, `Citations`, `FinalPromptView` | `sessions.list`, `session.get` | `session.*`, `tool.*`, live `model.chunk` | `SES-1`, `SES-2`, `SES-7`, `AGT-4`, `AGN-6`, `PMT-6`, `TOL-1` |
| **Agent channel** | `ChannelFeed`, `TopicFilter`, `MuteControl` | `agentChannel.list` | `agentChannel.posted` | `BUS-2`, `BUS-5` |
| **Prompts & memory** | `PromptEditor`, `InterviewChat`, `MemoryBrowser`, `MemoryReviewList` | `prompts.list`, `memory.list` | `memory.proposed`, `prompts.changed` | `PMT-2`, `PMT-10`, `MEM-3`, `MEM-4` |
| **Background** | `JobList`, `JobRow` | `jobs.list` | `job.*` | `JOB-1`, `JOB-2` |
| **Schedules** | `ScheduleList`, `ScheduleEditor`, `RunHistory` | `schedules.list` | `schedule.*` | `JOB-3`, `JOB-4`, `JOB-5` |
| **Tasks** | `TaskList`, `TaskRow`, `TaskEditor`, `DoItForMe` | `tasks.list` | `task.*` | `TSK-1`, `TSK-4` |
| **Reminders** | `ReminderList`, `ReminderEditor` | `reminders.list` | `reminder.*` | `REM-1` |
| **Activity** | `ActivityFeed`, `UndoAction` | `activity.list` | `activity.added` | `AGT-8`, `TOL-6` |
| **Logs** | `LogViewer`, `TraceView`, `EventInspector`, `FailedEvents` | `logs.search`, `trace.get` | live `log.line`, all events | `LOG-1`, `LOG-3`, `ARC-5` |
| **Settings** | `SettingsLayout`; sections: `Appearance`, `Profile`, `Preferences`, `Accounts`, `Models`, `Usage`, `ToolPermissions`, `SendChecks`, `Connectors`, `Rules`, `Notifications`, `HomeFolder`, `SystemContext`, `DataGuardRules`, `Network`, `About` | `settings.get` | `settings.changed` | `SET-1`, `SET-2`, `SET-3`, `SET-5`, `MOD-2`, `PRC-4`, `SDG-4`, `MDL-5`, `TOL-2`, `TOL-7`, `TOL-9`, `NTF-2`, `APP-11`, `HOM-6`, `PMT-11` |

## 6. Backend components

### Kernel

Shared infrastructure. No product logic.

| Component | Responsibility | Features |
|---|---|---|
| `contracts` | Types and schemas for all commands, queries, events and interfaces | `ARC-3` |
| `event-bus` | Publish, subscribe, durable log, catch-up, failed list | `ARC-2` |
| `database` | SQLite with encryption and WAL, migrations, single writer, automatic backup, recovery | `APP-9`, `APP-10` |
| `scheduler` | One timer for the next due item; wake and sleep handling | `JOB-7`, `JOB-3` |
| `job-runner` | Background work: progress, pause, retry, resume | `JOB-1`, `JOB-2`, `ARC-6` |
| `logging`, `tracing` | Structured logs, trace IDs, secret removal, 30-day retention | `LOG-1`, `LOG-3`, `ARC-5` |
| `config` | Defaults, overrides from Settings, validation | Section 1 |
| `home` | Find and validate Home, folder checks, path safety | `HOM-1`, `HOM-4`, `HOM-5`, `HOM-6` |
| `supervisor`, `system-events` | Start and restart processes; power and network events | `ARC-1`, `APP-3`, `APP-11` |
| `test-kit` | Fake model, fake IMAP, generated mailbox, contract suites | `ARC-7` |

### Product modules

Each owns its data, and exposes only commands, queries and events.

| Module | Owns | Example contract | Features |
|---|---|---|---|
| `settings` | Preferences, profile, sidebar layout | `settings.update` → `settings.changed` | `SET-1`, `SET-2`, `SET-3`, `SET-5`, `NAV-4` |
| `onboarding` | Setup progress, resume point | `onboarding.completeStep` | `ONB-1`, `ONB-2`, `ONB-4` |
| `mail-store` | Messages, folders, read state, categories | `mail.setCategory`; listens to `mail.received` | `PRC-1`, `NAV-2`, `ACC-8` |
| `threads` | Grouping, status, importance, stored summaries | `thread.summarize` → `summary.ready` | `THR-1`, `THR-3`, `THR-4`, `THR-5`, `THR-6` |
| `rules` | Fixed rules and evaluation | Listens to `mail.received` → `mail.ruleMatched` or `mail.needsTriage` | `PRC-4`, `PRC-6` |
| `attachments` | Classifier, hash cache, text extraction | Listens to `mail.received` → `attachment.classified` | `ATT-1`, `ATT-2` |
| `search` | Full-text index | `search.run`; listens to mail and document events | `SRC-1`, `THR-7` |
| `documents` | Library, uploads, folders, tags | `documents.upload` → `document.indexed` | `DOC-1`, `DOC-2`, `DOC-4` |
| `panels` | Panel definitions, boards, read-only filter queries | `panels.save`, `panels.results` | `PNL-1`, `PNL-3`, `PNL-5` |
| `tasks` | To-dos | `tasks.create` → `task.created` | `TSK-1`, `TSK-4` |
| `reminders` | Reminders and repeat rules | `reminders.create`; listens to due times | `REM-1` |
| `work-board` | Shared deadlines, status, drafts, who handled what | `board.record`, `board.query` | `BUS-1` |
| `channels` | User channel and agent channel messages, grouping, limits | `channel.reply`; `agentChannel.post` | `CHN-1`, `CHN-3`, `CHN-5`, `CHN-7`, `BUS-2`, `BUS-4`, `BUS-5` |
| `notifications` | Rules for what interrupts, quiet hours, history | Listens to `mail.triaged` → `notification.raised` | `NTF-1`, `NTF-2`, `NTF-5` |
| `schedules` | User schedules and the defaults | `schedules.save` → `schedule.due` | `JOB-3`, `JOB-4`, `JOB-5` |
| `today` | Combines data for the Today screen | `today.view` | `NTF-3` |
| `activity` | Readable agent activity and undo | `activity.undo` | `AGT-8` |

### Connectors

| Connector | Parts | Contains | Features |
|---|---|---|---|
| `connector-host` | Runs connectors through the shared interface; lists tools, skills and resources | | `MOD-1`, `MOD-2` |
| `mail` | `ImapClient`, `SyncEngine`, `IdleListener`, `MessageParser`, `SmtpSender`, `AccountConfig`, tools, skills, resources | Search, read thread, draft, send, set category, move; triage, draft, summarize skills | `ACC-1`, `ACC-3`, `ACC-6`, `ACC-8`, `PRC-8` |
| `pst` | `PstReader`, `ImportJob`, `Dedupe`, on-demand attachments | Search, read resources; pause and resume | `PST-1` |

### Agent

| Component | Responsibility | Features |
|---|---|---|
| `agent-runtime` | LangGraph graphs, checkpoints, one agent with different configurations, entry points with context | `AGN-3`, `AGN-10`, `AGT-3`, `AGT-4` |
| `session-manager` | Parallel sessions, queue and limit, state machine, compression of long sessions | `SES-1`, `SES-2`, `SES-7`, `ARC-6` |
| `mail-agent` | Triggered by `mail.needsTriage`; own queue, burst grouping, run records | `AGN-3`, `AGN-4`, `AGN-5`, `AGN-6` |
| `daily-prep` | Nightly run from the work board, within its token limit | `JOB-4` |
| `interview` | Setup interview conversation that writes personalized prompts | `PMT-10` |
| `prompt-builder` | Assembles the five layers, with system context | `PMT-1`, `PMT-2`, `PMT-6`, `PMT-11` |
| `memory` | Files in Home, index, relevance, proposals | `MEM-1`, `MEM-3`, `MEM-4` |
| `model-gateway` | The one door for model calls: guard, limits, provider, logging, failure handling | `ARC-4`, `MDL-5`, `MDL-6` |
| `providers` | `InternalApiProvider` (with JSON fallback), `GeminiProvider` | `MDL-1` |
| `data-guard` | Masking, restoring, token map, rules, flagged-request errors | `SDG-1`, `SDG-2`, `SDG-3`, `SDG-4`, `SDG-8`, `SDG-9` |
| `tool-gateway` | The one door for tools: restore values, permission check, approval, logging, masking results | `ARC-4`, `AGT-5`, `TOL-3` |
| `policy` | Permission table, untrusted content rule, folder limits, send checks | `TOL-2`, `TOL-5`, `TOL-7`, `TOL-9` |
| `tools` | `Read`, `Write`, `Edit`, `Command`, snapshots for undo, app tools (ask, suggest, tell, notify, approval) | `TOL-1`, `TOL-6`, `AGT-5` |

### Web client and security

| Component | Responsibility | Features |
|---|---|---|
| `local-server` | FastAPI on `127.0.0.1`, `Host` and `Origin` checks, per-install token | `ARC-1` |
| `desktop/` (Stage 5) | Electron window, pop-up window, tray, start at login, single instance, Python sidecar | `APP-1`, `APP-3` |
| `ui/client` | Typed commands and queries, event subscriptions, cache updates | `ARC-2`, `ARC-3` |
| `diagnostics` | Proxy, health check, support report | `APP-11` |

## 7. Build plan

Each step ends with something you can see working. **Unslop and the quality bar apply to every screen.**

### Stage 0: Foundation

Status: built except 0.5. Agent host and Heavy jobs processes, the backend supervisor, live events and the per-install token arrive with the first features that need them.

| # | Build | Done when |
|---|---|---|
| 0.1 | `frontend/` and `backend/` projects with pinned dependencies; `uv` for Python; ruff, pytest, `import-linter`, type checks and the no-hardcoding check | A hardcoded color fails the check |
| 0.2 | Local server with security checks, config, logging | A request from another origin is refused |
| 0.3 | Contracts, event bus, database, migrations | An event survives a crash and is delivered after restart |
| 0.4 | Theme system with `nexus-light` and a `nexus-dark` draft, `ui/strings`, typed client, gallery | Changing one theme file value restyles the app, with no component edits |
| 0.5 | Install unslop; run it on v9; write `DESIGN_DIRECTION.md` | You approve the direction |
| 0.6 | Proof: Settings → change theme, seen in the event inspector | Works through every layer, and survives a reload |

### Stage 1: Shell

| # | Build | Done when |
|---|---|---|
| 1.1 | Primitives and `AppShell`, in the gallery | Every state passes the quality bar |
| 1.2 | Home folder module and recovery screen | Choosing and losing Home both behave correctly |
| 1.3 | Landing, onboarding, and entry into the app | A new user reaches an empty Today in a polished flow; the Mail, Model and Interview steps connect in later stages |
| 1.4 | Settings: Appearance, Profile, Preferences, Home, Network | Themes, density and text size apply instantly |
| 1.5 | Sidebar with drag; Logs and trace view; notification center | Layout is remembered, and logs can be filtered live |

### Stage 2: Mail

| # | Build | Done when |
|---|---|---|
| 2.1 | Connector host, Mail connector, sync, IDLE | Gmail test account syncs, and new mail appears with no polling |
| 2.2 | Mail store, Inbox, safe display | A 100,000-message mailbox meets speed targets |
| 2.3 | Threads and Thread view | Real threads group correctly, including Outlook ones |
| 2.4 | Rules and editor | Rules categorize mail, with "Why is this here?" |
| 2.5 | Attachments, Documents, Search | Signature images are hidden; attachments are searchable |
| 2.6 | Send, drafts, two-way state, send checks | Actions match on the server |
| 2.7 | PST connector and Archive | A multi-GB PST imports in the Heavy jobs process without slowing the UI, and resumes |
| 2.8 | Panels with filters and drag | Starter panels update live, and layout persists |

### Stage 3: Agent

| # | Build | Done when |
|---|---|---|
| 3.1 | Providers, model gateway, data guard | Tests show no raw sensitive value reaches a provider, and tool arguments restore correctly |
| 3.2 | Prompt builder, system context, memory, editors | "View final prompt" shows each layer, masked and real |
| 3.3 | Policy, tool gateway, tools, approval cards | Every permission case passes its test; untrusted sessions always ask |
| 3.4 | Runtime, sessions, Session screens | Three sessions run in parallel, and resume after a restart |
| 3.5 | Mail agent, burst handling, thread summary | Every non-rule email triaged live; a burst groups correctly |
| 3.6 | Setup interview joined to onboarding | Interview writes editable prompts; Skip works |
| 3.7 | User channel, agent channel, work board | Ask, Suggest and Tell work; sessions message each other, and permissions don't transfer |
| 3.8 | "Ask agent" everywhere, drafts, activity with undo | Context is attached and removable |

### Stage 4: Daily work

| # | Build | Done when |
|---|---|---|
| 4.1 | Scheduler, Time check, Schedules screen | Reminders fire on time, including after sleep, with no polling |
| 4.2 | Daily prep | Morning shows prepared work, within the token limit |
| 4.3 | Tasks, Do it for me, Reminders | Agent proposes, and user approves |
| 4.4 | Today, urgent pop-up, quiet hours, usage view | Full day of use on your own mail |
| 4.5 | Final unslop pass across all screens | Quality bar passes everywhere |

### Stage 5: Electron

| # | Build | Done when |
|---|---|---|
| 5.1 | Electron shell, window, tray, start at login, single instance | The app behaves like a desktop app on Mac |
| 5.2 | Bundled Python sidecar, supervised and restarted | Backend starts and recovers, with no Python installed on the machine |
| 5.3 | Urgent mail pop-up window, native theme colors | Mica and vibrancy follow the theme |
| 5.4 | Windows installer without admin rights; Windows CI and VM checks; test on a corporate laptop | Antivirus and AppLocker allow it |

## 8. Decisions needed

| Decision | Recommendation |
|---|---|
| Approve the v9 readability corrections in section 2 | Yes: slightly darker text and an 11px minimum |
| Dark theme direction | Warm dark, built from v9's island colors (`#121010` to `#2E2620`), previewed in Stage 0 |
| Buy AICSS Pro | No: free sources cover the need |
