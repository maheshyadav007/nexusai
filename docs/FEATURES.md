# NexusAI Feature List

Feature set for review, grouped by how the pieces depend on each other. Context: [`PRODUCT_VISION.md`](PRODUCT_VISION.md), stack: [`TECH_STACK.md`](TECH_STACK.md), design: [`ARCHITECTURE.md`](ARCHITECTURE.md), parts and build order: [`COMPONENT_PLAN.md`](COMPONENT_PLAN.md).

## Release targets

| Target | Goal |
|---|---|
| **MVP** | One person can use it daily at work: connect mail, have every important email triaged with their own prompts, talk to the agent, approve its work, and trust that sensitive data is protected |
| **Next** | Fuller workspace: artifacts, watches, external connectors, meaning search and the first work helpers |
| **Later** | Company-wide and advanced: shared brain, agent-written panels, meeting recording, playbooks |

**MVP build stages**, each usable before the next starts:

0. **Foundation:** processes, event bus, database, theme system, build checks
1. **Shell:** app, Home folder, landing and onboarding, themes, settings, logs, encrypted store
2. **Mail:** Mail and PST connectors, sync, threads, rules, attachments, search, documents, panels
3. **Agent:** setup interview, prompts, memory, data guard, permissions, tools, sessions, Live mail agent, user channel, agent channel, approvals
4. **Daily work:** work board, Daily prep, Time check, schedules, tasks, reminders, notifications
5. **Electron:** desktop app wrapping the same UI and backend, Windows installer

| Part | Sections |
|---|---|
| **A. App foundation** | App & security · Home folder · Landing & onboarding · Navigation & personalization · Settings · Logs · Architecture foundation |
| **B. Connectors** | Connector system · Mail: accounts, processing, attachments, threads · PST · Files & Calendar |
| **C. Agent core** | Agent · Prompts · Memory · Sessions · Tools & permissions · Models · Sensitive data guard · Shared context |
| **D. Automation** | Default runs · Schedules & watches · Background |
| **E. Workspace** | Today & user channel · Notifications · Panels · Search · Documents · Tasks & reminders · People · Notes · Artifacts |
| **F. Work helpers** | Commitments, project pages, repetition finder and more · Meetings |

---

# A. App foundation

## A1. App & security

| ID | Feature | Pri |
|---|---|---|
| APP-1 | Web app first (Next.js UI + local Python backend), then an Electron desktop app for Windows and macOS, v9 design | MVP |
| APP-3 | Backend keeps running with the browser closed, so agents continue; once in Electron, tray / menu-bar icon, start at login, single instance | MVP |
| APP-9 | Encrypted local store with a recovery key, so a moved Home opens on a new PC; data stays on the device except model calls | MVP |
| APP-10 | Automatic backup before upgrades; recovery from a damaged database | MVP |
| APP-11 | Network settings and diagnostics: proxy, health check, "copy support report" | MVP |
| APP-12 | Full keyboard use, including an alternative to every drag | MVP |
| APP-2 | Command bar (Ctrl/⌘ K): search, ask, create | Next |
| APP-7 | Auto-update | Next |
| APP-8 | App lock: OS login or Windows Hello on open and after idle | Next |
| APP-14 | Manual backup and restore of Home | Next |
| APP-15 | Screen reader support and high-contrast theme | Next |
| APP-16 | Reset: removes everything NexusAI made and every saved credential, and starts setup again, after typing a word to confirm. Only known folders are removed, and downloaded models can stay | MVP |
| APP-13 | Retention settings; keep local mail within company policy | Next |

## A2. Home folder

The user picks one **NexusAI Home**. Everything the app stores lives there, except model and connector sign-ins and this Home's own key, which stay in the OS credential store. Mail accounts, passwords included, are in an encrypted file here. There is one Home per user, with no separate per-project spaces. A small pointer file in the OS app-data folder records where Home is.

```text
<NexusAI Home>/
  home.json     format version and ID of this Home
  system/       app only: nexusai.db, search indexes, attachment cache, ONNX models, mail-accounts.enc, rules.json, logs
  prompts/      personalized and agent prompts, in markdown
  memory/       user and agent memory files, in markdown
  documents/    uploaded documents
  artifacts/    artifacts made by the agent, with their versions
  scratch/      the agent's working area, one folder per task
    <task-id>/
```

Default location is `~/NexusAI` on macOS and `%USERPROFILE%\NexusAI` on Windows, not Desktop or Documents, which iCloud and OneDrive often sync.

| ID | Feature | Pri |
|---|---|---|
| HOM-1 | Choose Home on first run, with the default offered; block network drives and unwritable folders, warn on cloud-synced folders, show free space | MVP |
| HOM-4 | "Home not found" screen at startup: locate it or choose another; never silently create an empty one | MVP |
| HOM-5 | By default the agent's file tools reach only `scratch/`, `memory/`, `documents/` and `artifacts/`; `system/` only through app tools; `prompts/` can be read but changed only through the prompt system; `..` and symlinks resolved before every check | MVP |
| HOM-6 | One scratch folder per task, with "Open folder"; optional auto-delete timer, default **Never** | MVP |
| HOM-3 | Change Home in Settings: move with progress, verify, then remove the old copy; or open an existing Home | Next |
| HOM-7 | Storage view: space used by database, models, cache and scratch; clear cache and scratch | Next |

## A3. Landing & onboarding

A screen inside the app, following the v9 look and the chosen theme. The flow: **Landing → Home folder → Theme → Profile → Mail → Model → Setup interview (can skip) → Email priorities → PST import (can skip) → Tool permissions → App.** The result is a guided path into the app, ending on Today.

| ID | Feature | Pri |
|---|---|---|
| ONB-1 | Landing screen on first launch: what NexusAI does, data stays on this device, "Get started"; returning users go straight to Today | MVP |
| ONB-2 | Short guided setup with progress, back and resume if closed midway: data, you, mail, model, search model, how much the agent may do. Live checks of mail login, model and folder, with errors in plain language. The interview, priorities and old mail wait in a dismissible checklist on Today | MVP |
| ONB-4 | Sync and PST import continue in the background so the user enters the app right away | MVP |
| ONB-6 | Short dismissible tour of the app on first entry | Next |

## A4. Navigation & personalization

```text
Today
Mail         Inbox · Categories · Sent · Drafts · Archive (PST)
Documents    All · Uploaded · From email
Agent        Sessions · Agent channel · Prompts & memory · Background · Schedules
Planner      Tasks · Reminders
Panels
Logs
Settings
(top bar)    Notification center · Approvals

Added with Next and Later features: Artifacts, Agents, Notes, Meetings, Projects, People, Command bar
```

| ID | Feature | Pri |
|---|---|---|
| NAV-1 | Sidebar as above: collapsible, with unread and running counts | MVP |
| NAV-4 | Personalize by dragging: reorder, nest and move folders and sections, hide what isn't used; "Reset layout" restores the default. Dragging a folder only rearranges the sidebar; dragging an email into a mail folder moves it and syncs to the server | MVP |

## A5. Settings

| ID | Feature | Pri |
|---|---|---|
| SET-1 | Appearance: light, dark or follow system; accent color, density, text size; applies instantly | MVP |
| SET-2 | Profile: name, role, signature, tone, VIPs, About me | MVP |
| SET-3 | Preferences: default screen, date and time format, start at login | MVP |
| SET-5 | Accounts, Models, Tool permissions, Connectors, Rules, Notifications and quiet hours, Home, System context, Sensitive data rules, About | MVP |
| SET-8 | Language and custom keyboard shortcuts | Next |
| SET-6 | Search across settings | Next |
| SET-7 | Export and import settings | Later |

## A6. Logs

Activity (AGT-8) is the readable story of what the agent did. Logs are the technical record.

| ID | Feature | Pri |
|---|---|---|
| LOG-1 | Log viewer: app, agent, tool calls, sync and errors, filtered by level, connector, session and time, with a live view; every tool call recorded with its input, result, duration and who approved it | MVP |
| LOG-3 | Passwords and tokens always removed; mail bodies left out unless debug logging is on; files kept for 30 days | MVP |
| LOG-4 | Export logs for support, and audit log export for IT | Next |
| LOG-5 | What left this device: a plain record of every model call (what was sent, to which model, when, why), exportable for IT | Later |

## A7. Architecture foundation

Built before any feature. Details are in [`ARCHITECTURE.md`](ARCHITECTURE.md).

| ID | Feature | Pri |
|---|---|---|
| ARC-1 | Separate processes for UI, Core, Agent host and Heavy jobs, restarted after a crash, so heavy work can't freeze the UI; the local server accepts only the app's own requests | MVP |
| ARC-2 | Event bus across frontend and backend: anything can emit, and all relevant parties react, with no polling; important events saved, so nothing is lost after a crash or reload | MVP |
| ARC-3 | Modular design: each module has a typed contract of commands, queries and events, enforced by a build check; swappable connectors, models and tools share one interface | MVP |
| ARC-4 | One door each for model calls, tool calls and database writes, so safety, limits and logging can't be skipped | MVP |
| ARC-5 | Debugging: a trace ID on all work, a trace view of everything that happened to an item, a live event inspector, and coded errors | MVP |
| ARC-6 | Explicit state machines for sessions, sync, jobs and approvals | MVP |
| ARC-7 | Automated tests at every level, including a fake model and Windows CI, with speed targets that fail the build if missed | MVP |

---

# B. Connectors

## B1. Connector system

Every data source is a connector: an MCP server with its own tools, skills and resources. Mail is simply the first one, built in. The agent works the same way with built-in, public and internal connectors.

| Part | What it is | Mail connector example |
|---|---|---|
| **Tools** | Actions the agent can call | Search, read thread, draft, send, set category, move |
| **Skills** | Packaged know-how the agent loads when needed | Triage an email, draft a reply, summarize a thread |
| **Resources** | Data the agent and panels can read | Messages, threads, attachments, folders |
| **Events** | Signals that trigger agents and watches | New mail, reply received |

| ID | Feature | Pri |
|---|---|---|
| MOD-1 | Connector system. Email and PST are built in, and report name, status and on/off the same way MCP servers do, with their tools staying direct behind the one tool door | MVP |
| MOD-2 | Connectors in Settings: status, sync progress, tools, skills and resources of each, on/off | MVP |
| MOD-4 | Add an MCP server by web address on the Connectors page or in Settings, with a token in the OS credential store, a test that lists its tools first, and a public or internal label. Local command servers and OAuth come later | Done (by address) |
| MOD-7 | (Built, except the allowlist.) Connector safety: new tools start as Ask; results count as untrusted content (TOL-5); re-approve if tools or descriptions change; warning that public connectors receive real values, since masking applies only to model calls; company policy file can limit connectors to an approved list | Next |
| MOD-9 | Manage skills: turn off a connector's skills, or add your own | Next |
| MOD-5 | NexusAI as an MCP server for other agents | Later |

## B2. Mail: accounts & sync

| ID | Feature | Pri |
|---|---|---|
| ACC-1 | Mail accounts in one encrypted file, `mail-accounts.enc` (corporate, Gmail test). Only a server name, username and password are needed, and the rest is worked out, with details to override it. Connecting tries the login first | MVP |
| ACC-3 | IMAP sync: newest N first, then backfill in the background; live new mail via IDLE; reconnects after sleep or network change, and resumes after restart | MVP |
| ACC-3a | Connecting tries the login, shows how many different emails are on the server across every folder, and asks how many of the newest to download (suggestion in `mail.suggested_pull`). That sets a budget. New mail always comes down, and an email already here never uses any | MVP |
| ACC-3b | **Pause** holds everything, including new mail. **Stop** ends older mail while new mail keeps coming. **Get more** brings N more, from all folders in turn or from one. Available from the account, the Schedules page and the Cockpit, and they survive restarts | MVP |
| ACC-3c | Each check runs at most `mail.check_every_seconds` apart (a minute), and sooner when the server announces new mail. The Schedules page and Cockpit show what's on the server, what's here, the last and next check, and what the last check found and pulled. Checks that find nothing add nothing to the event log | MVP |
| ACC-3d | One email, many folders. Every server folder syncs, including Gmail labels. An email is stored once, with a location per folder, so read and flag state are shared. Mail already here is filed under its other folders without downloading. Add to a folder and remove from one work both ways, and a conversation can be in several categories | MVP |
| ACC-3e | Never delete on the server: on by default, per account. `ImapSession` refuses every delete, expunge and move to Trash, Trash here stays on this computer, and drafts aren't copied to the server | MVP |
| ACC-3f | Spam and Trash stay apart: visible in their own folders, never judged by an agent, searched, indexed or listed in Documents | MVP |
| ACC-3g | Kinds of mail by header, with no model: Promotions, Updates, Forums, and Social on public mail services. Mail from the person's own company domain is never Promotions | MVP |
| ACC-6 | Send, reply and forward via SMTP, only after approval; Sent and Drafts folders, including agent drafts awaiting approval | MVP |
| ACC-8 | Two-way mail state: read, flag, move, delete and drafts sync with the server | MVP |
| NAV-2 | Mail categories: built-in (Needs you, FYI, Newsletters, Automated) and user-created; set by rules or the agent | MVP |
| ACC-5 | Choose folders to sync (Inbox, Sent, others) | Next |
| ACC-9 | Shared and delegated mailboxes | Next |
| ACC-7 | Several profiles active at once | Later |

## B3. Mail: processing & rules

| ID | Feature | Pri |
|---|---|---|
| PRC-1 | Normalize every message into one model; clean body for the agent by stripping quoted replies, disclaimers and signature text, keeping the original for display | MVP |
| PRC-4 | Fixed rules: built-in header rules (auto-generated, no-reply, lists), plus user rules in `rules.json` with an editor: subject, body, sender, header and attachment conditions → category, mark read, skip agent, notify, tag | MVP |
| PRC-6 | "Why is this here?" on every message (rule name or agent reason) | MVP |
| PRC-7 | Safe mail display: sanitize HTML, block scripts and remote images by default | MVP |
| PRC-8 | Detect encrypted and signed mail (S/MIME), and say plainly when it can't be read | MVP |
| PRC-9 | Warn on lookalike senders and links | Next |

## B4. Mail: attachments & inline images

Every email has a mix of signature logos, real attachments and meaningful inline images. Each part is classified **before** anything expensive runs:

| Kind | How we detect it | What we do |
|---|---|---|
| **Signature / branding** (corp logo, social icons, banners) | Inline (`Content-ID`), small file / small dimensions, **same image hash seen across many emails** from that sender or domain, sits inside the signature block | Hide from the agent and attachment lists; never OCR; stored once by hash |
| **Meaningful inline image** (festive greeting, brochure, poster, screenshot) | Inline but large, or the body is mostly image with little text, or first time this hash appears | OCR + image description (ONNX), result added to the message text and search |
| **Real attachment** (PDF, Office, images, zip) | `Content-Disposition: attachment` | Extract text (PDF, Word, Excel, PowerPoint), OCR scanned PDFs/images, index; show in Documents |
| **Calendar invite** (`.ics`) | MIME type | Parse into a calendar event |
| **Risky** (executables, macros, password-protected archives) | Extension / type | Flag, never open or extract |

| ID | Feature | Pri |
|---|---|---|
| ATT-1 | Attachment classifier as above, with image-hash cache across all mail; "Show hidden images" per message, in case a signature guess is wrong | MVP |
| ATT-2 | Text extraction from PDF and Office attachments, lazily: new mail first, history only when opened or searched | MVP |
| ATT-3 | OCR and description of meaningful images and scanned PDFs (ONNX); results searchable | Next |

## B5. Mail: threads

The thread is the main unit of work. People read threads, and the agent judges them, rather than isolated emails. Each email still keeps its own record for search and "Why is this here?".

| ID | Feature | Pri |
|---|---|---|
| THR-1 | Reliable grouping: `References` and `In-Reply-To`, Outlook's `Thread-Index`, then subject and participants as a fallback | MVP |
| THR-2 | Thread view: newest message open, older ones collapsed, quoted text hidden, with people added or dropped along the way marked | MVP |
| THR-3 | Thread summary on demand: nothing is generated until the user clicks **Summarize**; the result is stored and reused. It covers what happened, where it stands and what's being asked of the user. When newer messages exist, it shows "3 new messages since this summary" with an Update button that reads only those | MVP |
| THR-4 | Category and importance belong to the thread, and a new message can raise or lower them; the change and its reason are shown | MVP |
| THR-5 | Thread status: waiting on you, waiting on others, resolved or FYI, updated by the agent and changeable by the user | MVP |
| THR-6 | Long threads: the agent receives recent messages within a size limit, plus the stored summary if one exists, and can look up older ones when needed | MVP |
| THR-7 | Only each message's own new text is indexed, so search returns one hit per thread instead of repeats from quoted text | MVP |
| THR-9 | Drafts use the whole thread, and the user chooses who gets the reply; warns if someone was dropped | MVP |
| THR-8 | Missing history: fetch unsynced older messages on demand and mark the summary as partial until then | Next |
| THR-10 | Mute, follow and snooze a thread; a muted thread comes back if the user is directly addressed | Next |
| THR-14 | Manually merge and split threads | Next |
| THR-11 | Forwarded chains and side branches: separate earlier messages inside a forward, and show when a thread splits | Next |
| THR-13 | Files panel: every attachment in the thread in one list, with the latest version marked (WRK-3) | Next |

## B6. PST archives

| ID | Feature | Pri |
|---|---|---|
| PST-1 | PST connector: import one or more PST files (GBs) in the background with pause and resume, from onboarding or Settings; keeps folder structure; dedupes against IMAP mail by `Message-ID`; joins existing threads; index only, with no AI triage; attachments read on demand, not copied | MVP |

## B7. Files & Calendar

| ID | Feature | Pri |
|---|---|---|
| MOD-3 | Calendar connector: show meetings, accept or decline invites, show free time | Next |
| FIL-1 | Files connector: watch chosen local folders; index PDF, Office, text and images; shown in the library, deduped by hash | Next |
| FIL-3 | Suggest filing and renaming (approval required) | Later |

---

# C. Agent core

## C1. Agent

There is one agent, invoked from different places with the right context. The Mail agent and others are configurations of it, each with its own instructions, memory, model, tools and triggers. Triggers: **new email** (or another event), **schedule**, **manual**.

```text
New email → fixed rules → Mail agent → category, importance, summary, reason → inbox, notification, tasks
                              ↑
       system + agent + personalized prompts + relevant memory
```

Rules run first and cost nothing; mail they mark "skip agent" never reaches the model. A personalized prompt tells the agent how to judge; a rule is an exact instruction that always applies.

| ID | Feature | Pri |
|---|---|---|
| AGN-3 | Mail agent: triggered live by every new email that escapes the fixed rules, reading it with recent thread messages (THR-6) and giving category, importance, summary, key facts and suggested action; can propose tasks, reminders, drafts and memory; records deadlines and thread status on the work board; has no Command or send tool | MVP |
| AGN-3a | Each judgement goes by, strongest first: what the person said, what they corrected, their memory, what the app counted (To or Cc, who they reply to, what they open), notes learned from mail, then the email itself | MVP |
| AGN-3b | Sets who has the next move, what they'd do (reply, do, decide, read), when to chase, and whether to interrupt, each with a reason. Interrupting is decided apart from importance, and at most three questions stay open | MVP |
| AGN-3c | Sending takes a conversation off the person's plate and works out what comes next. A follow-up date that passes tells them once, on Today with a draft button. A reply moves it back. None of this needs a model except the date | MVP |
| AGN-3d | Automated mail skips the model unless what it says could cost the person something, or it's in a conversation they wrote in | MVP |
| AGN-3e | A broadcast reaches the model as a count, and it can search the list if who else got it matters | MVP |
| AGN-3f | Weekly inbox review, and after reading past mail: recommends where whole groups of mail should go, with the app's own counts. Nothing moves until the person agrees. The same correction three times offers to make it automatic | MVP |
| AGN-3g | A morning brief on Today, from what's already judged | MVP |
| AGN-3h | "What it knows" shows everything the agent is told, in order and how far it's trusted; each learned note with its source, to confirm or remove; corrections and who they write to. "What it sees" shows the exact text for any conversation, without calling a model | MVP |
| AGN-3i | `make eval-mail` runs made-up emails through the real model to check the prompts | MVP |
| AGN-3j | Morning brief card at the top of Today, with like, dislike and a request box. Each new brief is told the person's words and reactions, and they're listed under What it knows | MVP |
| AGN-3k | Needs you: each action blocks its row, shows it running, then says how it went. Select several, then Do it or Decline in bulk. Sending mail and running commands stay one at a time | MVP |
| AGN-3l | Agents list on the Agent channel page: running, active, finished, off and removed agents, what starts each and when it runs next | MVP |
| SRCH-5 | Search understands `from:`, `to:`, `subject:`, `has:attachment`, `is:unread`, `in:`, `before:`, `after:`, `category:` and "exact phrases", ignores common words, finds mail with only some of the words, corrects typos and says so, ranks a subject match and the person's own conversations first, and leaves out weak matches by meaning | MVP |
| SRCH-6 | Opening a result keeps the results beside it, and Back returns to the same search and filters | MVP |
| DOC-9 | Older attachments are read in the background, so search reaches inside them. A match in a file's name ranks above one in its text | MVP |
| AGN-4 | Burst handling: a single email starts right away with no timer. Emails arriving during a run wait, then go together in the next run, grouped by thread and capped per run. Its own queue, separate from the session limit; catches up in order after being offline or if the model is unavailable | MVP |
| AGN-5 | Runs from setup onward only; older mail is triaged only on request, with an estimate of the work first | MVP |
| AGN-6 | Mail agent appears as one entry in Sessions; each email has its own run record, reachable from "Why is this here?" | MVP |
| AGN-10 | Agent from anywhere: "Ask agent" on any email, thread, task, document, notification or text selection opens a session with that item attached as context, which the user can see and remove | MVP |
| AGT-3 | Draft replies in the user's tone, shown with "why" | MVP |
| AGT-4 | Ask anything across mail, attachments and documents, with sources | MVP |
| AGT-5 | App UI exposed as tools alongside connector tools: ask, suggest, tell, notify, approval card, pin | MVP |
| AGT-8 | Activity log with undo where possible | MVP |
| AGN-1 | Agents screen: on/off, model per agent, tools, triggers and last run. In the MVP this is a simple Settings section | Next |
| AGN-9 | Shadow mode: the agent acts on nothing and only records what it would have done, then reports how often it matched the user, per job. Duration adjustable, default 3 days; can also be started ad hoc, such as after a prompt or model change, and stopped early. The report suggests permissions; the user decides | Next |
| AGN-8 | Triage quality score from user corrections, plus a saved test set for prompt changes | Next |
| AGN-7 | User-created agents with their own prompt, tools and triggers | Next |

## C2. Prompt system

Every agent run builds its prompt from these layers, top to bottom. A higher layer wins any conflict.

| Layer | What it holds | Who changes it | Stored in |
|---|---|---|---|
| **1. System prompt** | Identity, safety and tool rules, plus system context injected once (PMT-11); shared by all agents | Us, with app updates; read-only to the user | App |
| **2. Agent prompt** | One agent's job and output format | Built-ins ship with the app; the user can add instructions | `prompts/agents/` |
| **3. Personalized prompts** | About me, plus how to handle email: categories, importance, per-sender and per-topic instructions | User; the agent can only propose changes | `prompts/personal/` |
| **4. Memory** | Relevant user and agent memory | See C3 | `memory/` |
| **5. Task content** | The email, document or request being handled. Treated as data: instructions inside an email are never followed | Nobody; built per run | Not stored as a prompt |

| ID | Feature | Pri |
|---|---|---|
| PMT-1 | Prompt builder that assembles the layers in this order for every agent run | MVP |
| PMT-2 | Personalized prompt editor: About me, one prompt per mail category, importance guide, per-sender and per-topic instructions; edits made outside the app are picked up | MVP |
| PMT-10 | Setup interview: the agent asks about the user's role, people and priorities, then writes personalized prompts for review. An optional onboarding step with Skip; can be run again any time from Settings | MVP |
| PMT-3 | "Email priorities" onboarding step with a starter set the user edits | MVP |
| PMT-6 | "View final prompt" for any run: exactly what was sent to the model, by layer, with the masked version and the real values side by side | MVP |
| PMT-11 | System context injected into the system prompt only: OS and version, CPU type, shell and its version, installed tools such as Python and Git, date and time zone, Home path, allowed folders and known limits such as no admin rights, so the agent writes commands that fit this computer. Refreshed at session start, visible in Settings, and passed through the data guard | MVP |
| PMT-4 | Test a change on recent mail before saving: shows which emails would change category or importance | Next |
| PMT-5 | Version history and restore for agent and personalized prompts | Next |
| PMT-7 | Learning from corrections: when the user recategorizes mail or repeats an action, the agent proposes a prompt change or a rule; applied only on approval | Next |
| PMT-9 | Export and import personalized prompts; company prompt packs distributed by IT or a team lead, sitting below the user's own prompts | Later |

## C3. Memory system

| Level | What it holds | Used by | Lifetime | Stored in |
|---|---|---|---|---|
| **Session memory** | The current conversation and steps | That session | With the session | `system/` (session state) |
| **Agent memory** | What one agent learned about doing its job, such as "this sender's reports are routine" | That agent | Until deleted | `memory/agents/<agent>/` |
| **User memory** | Facts about the user and their work, such as projects and preferences | All agents | Until deleted | `memory/user/` |

Mail, documents and notes are not memory. Agents reach them through search.

| ID | Feature | Pri |
|---|---|---|
| MEM-1 | Session, agent and user memory as above; only memories relevant to the task are loaded, within a size limit | MVP |
| MEM-3 | Memory browser: view, edit, delete and search, grouped by level, with the source of each entry; edits made outside the app are picked up | MVP |
| MEM-4 | Runs that read mail or other untrusted content can only **propose** memory; proposals wait in a review list (TOL-5) | MVP |
| MEM-5 | Runs show which memories they used; "Forget this" from there | Next |
| MEM-6 | Agent suggests merging duplicate and outdated memories; user approves | Next |

## C4. Sessions

| ID | Feature | Pri |
|---|---|---|
| SES-1 | Several sessions running in parallel, each with its own history, scratch folder and model; limit on those running at once (default 3), extras queued | MVP |
| SES-2 | Sessions view: status (running, waiting for approval, done, failed), current step, time and token use; open, stop, resume, rename, search, archive and delete. Work continues when the user switches away and resumes after a restart | MVP |
| SES-7 | Long chats send the model only recent messages, with summarizing available automatically or on request, chosen in Settings and per schedule. Originals always stay in the chat | MVP |
| SES-6 | Warn when two sessions change the same file outside `scratch/` | Next |

## C5. Tools & permissions

Tools: **Read, Write, Edit** and **Command** (zsh on macOS, PowerShell on Windows). With permission, the agent can work across the whole computer.

| Default | Read | Write / Edit | Command |
|---|---|---|---|
| Home (except `system/` and `prompts/`) | Allow | Allow | Ask |
| Folders the user added | Allow | Ask | Ask |
| Rest of the computer | Ask | Ask | Ask |

| ID | Feature | Pri |
|---|---|---|
| TOL-1 | Read, Write, Edit and Command tools, each a logged tool call; command output shown live, with timeout and Stop button | MVP |
| TOL-2 | Permissions per tool and per folder: Off, Ask or Allow; add folders outside Home with chosen rights; "Full computer access" is a separate setting, off by default | MVP |
| TOL-3 | Approval cards for every write and send: the exact command or file diff, the folder, the session and why; allow once or for this session; all pending approvals in one queue in the top bar | MVP |
| TOL-5 | **Untrusted content rule:** once a session has read mail, attachments or web pages, Command, sending and writes outside `scratch/` always ask, whatever the other settings | MVP |
| TOL-6 | File snapshot before each Write or Edit, for undo; commands are marked as not undoable | MVP |
| TOL-7 | Commands run with the user's own rights and are not sandboxed, so folder limits apply to file tools only; the Settings screen and the approval card say so | MVP |
| TOL-9 | Send checks, configured here with Off, Warn or Block: external recipient on an internal thread, "attached" with no attachment, new reply arrived since the draft was written. Applies to every send, with a short undo-send delay | MVP |
| TOL-10 | More send checks: confidential file going outside, angry tone | Next |
| AGT-6 | Autonomy levels (Observe → Suggest → Draft → Act) as one-click presets for the permission table, global and per source or action | Next |
| TOL-8 | Company policy file can turn off Command or Full computer access | Next |

## C6. Models

| ID | Feature | Pri |
|---|---|---|
| MDL-1 | Model providers: ChatGPT subscription sign-in (for testing), internal API through LiteLLM (no tool calling, JSON fallback), internal API v2 (tools), Gemini (enterprise auth); choose from the models each one offers; every call passes through the data guard | MVP |
| MDL-5 | Model usage limits and view: tokens and cost per agent, daily cap, warning near it | MVP |
| MDL-6 | Model failure behaviour: mail, search and documents keep working, and queued agent work resumes when the model returns | MVP |
| MDL-7 | Automatic fallback to a second model | Next |
| MDL-3 | Local ONNX models for text embeddings, OCR and image description; downloaded once; CPU, or GPU when available (DirectML on Windows, CoreML on macOS); app works without them | Next |

## C7. Sensitive data guard

Sensitive values are swapped for tokens before any text goes to a model, and swapped back in whatever returns. **Everything stored and shown on the device keeps real values**, so masking happens only at the model boundary. People's names are not masked.

```text
Email     Ask kim.j@samsung.com, details at http://wiki.samsung.net/proj-x
To model  Ask <EMAIL_12>, details at <INT_URL_7>
Reply     Please contact <EMAIL_12> and open <INT_URL_7>
Shown     Please contact kim.j@samsung.com and open http://wiki.samsung.net/proj-x
```

| ID | Feature | Pri |
|---|---|---|
| SDG-1 | Mapper at one model gateway: every prompt layer, email, attachment text and tool result is masked before any model call, with no way around it; token map kept in the encrypted database, never logged or sent | MVP |
| SDG-2 | Reverse mapping on everything returning: streamed replies (including tokens split across chunks), drafts, and **tool call arguments before the tool runs**. Unknown or damaged tokens are never guessed: sends and tool calls using them stop until the user fixes them | MVP |
| SDG-3 | Stable tokens: the same value always gets the same token across runs, so an address in a personalized prompt matches the same address in an email | MVP |
| SDG-4 | Starter rules for email addresses, phone numbers (Indian and international), and links and hostnames containing `samsung`; rule editor in Settings with Mask or Block and a sample-text test | MVP |
| SDG-8 | When the internal LLM flags a request: stop that run and show a clear error message; a flagged email stays uncategorized and shows the error | MVP |
| SDG-9 | Images are not sent to models; only their locally extracted OCR text, which goes through the mapper | MVP |
| SDG-10 | Mail labelled "Confidential" goes only to approved or local models | Next |

## C8. Shared context & agent channel

Agents and sessions work as one team instead of each starting from nothing. A **work board** holds what is known, and an **agent channel** lets them tell each other things. This is separate from the user channel (E1), which is between agents and the user.

```text
Live mail agent ──writes──▶ Work board ◀──reads── Daily prep, sessions, Time check
Session A ──"Priya replied on the budget thread"──▶ Agent channel ──▶ Session B
```

| ID | Feature | Pri |
|---|---|---|
| BUS-1 | Work board: shared structured record of thread status, deadlines, open tasks, prepared drafts and who handled what; agents load only the parts relevant to their task, so work isn't repeated | MVP |
| BUS-2 | Agent channel, the backbone for agents working together, built on the event bus (ARC-2): an agent or session can message another or post to a topic; the receiver reads it at its next step. Messages point to items by ID instead of copying text, which keeps context small | MVP |
| BUS-4 | Permissions don't transfer: a message is data, never an instruction; a session receiving one from an agent that read mail counts as having read untrusted content (TOL-5), so the read-only Mail agent can't use another session's Command tool | MVP |
| BUS-5 | Limits on messages per run and on back-and-forth, counted against token limits, so agents can't loop; the channel is visible to the user, who can read, filter and mute it; every message is logged | MVP |

---

# D. Automation

## D1. Default runs

Only three things run by default, and they share what they know through the work board:

| Default | When | What it does |
|---|---|---|
| **Live mail agent** | Every email that escapes the fixed rules | Triage, plus recording deadlines and thread status on the work board as it reads |
| **Daily prep** | Nightly | One run: overnight drafts and reports, morning brief, and follow-ups and deadlines needing attention. Reads the work board instead of re-reading mail |
| **Time check** (uses no model) | At the next due time, using one timer rather than polling | Reads the work board for overdue items and reminders; raises a notification or an Ask. Also does backup, index upkeep and the scratch timer on its nightly pass |

| ID | Feature | Pri |
|---|---|---|
| JOB-4 | Daily prep: drafts, reports and briefs for mail that needs the user, ready to approve in one click at the start of the day. The user sets the time, the scope and a nightly token limit. A laptop that was closed catches up on wake. Nothing is sent without approval | MVP |
| JOB-7 | Time check as above | MVP |
| JOB-5 | The three defaults can each be turned off, retimed or edited | MVP |

## D2. Schedules & watches

| ID | Feature | Pri |
|---|---|---|
| JOB-3 | Schedules: one-time or recurring prompts ("every Friday summarize project X"), on/off, run history; missed runs happen on next wake | MVP |
| JOB-8 | Ready-made schedules to add with one click: end-of-day summary, weekly status draft, repetition finder, memory review; the agent can propose new ones | Next |
| JOB-6 | Watches: "when Priya replies on this thread, draft an answer", "if anything arrives about the Q4 audit, tell me". Watch a thread, person, topic or event, then act. Described in plain words or started with "Watch" on a thread or person; can end after the first match or on a date. Thread and person matches use no model; topic and event matches use the Mail agent's result. Actions follow the normal permissions | Next |

## D3. Background

Named "Background" and "Schedules" in the app so they aren't confused with Tasks, which are the user's to-dos.

| ID | Feature | Pri |
|---|---|---|
| JOB-1 | Background view: sync, PST import, indexing and agent runs, with progress, pause and cancel | MVP |
| JOB-2 | Work survives a restart and retries with backoff; failures reach the notification center | MVP |

---

# E. Workspace

## E1. Today & user channel

The main focus space on Today is a two-way channel between the agents and the user. Agents post three kinds of message:

| Kind | Purpose | Example | User can |
|---|---|---|---|
| **Ask** | Agent needs an answer or clarification | "Is Priya's budget thread urgent, or can it wait until Monday?" | Pick an option, type a reply, or skip |
| **Suggest** | Agent proposes something | "You've filed 8 of these reports. Make a rule?" | Accept, change, dismiss, or "don't suggest this again" |
| **Tell** | Agent shares something useful | "The vendor confirmed Friday, so I closed that task." | Open the source, or dismiss |

| ID | Feature | Pri |
|---|---|---|
| NTF-3 | Today: greeting and one-line brief, Needs you, Due, Important mail, Waiting on others, Since you last looked, and one status line linking to the Cockpit | MVP |
| NTF-7 | Cockpit: what's running, health of each part, what's coming up, and a filterable feed of what happened | MVP |
| NTF-7a | Work on a timer with no agent is listed once (`modules/agent/pipelines.py`), and shows on the Schedules page and in the Cockpit with Stop and Run now. Mail sync is the only one today | MVP |
| AGN-L1 | Once enough mail is here, or no more is coming, the Mail agent reads the newest K emails rules didn't catch (`agent.learn_emails`, 400), oldest first. Each is judged, but can't notify, ask or add work. It keeps notes in `memory/agents/mail/learned.md`, which only it reads, always as untrusted data, and the person can edit. It then tells the person what it learned and goes live on new mail and the hourly check | MVP |
| AGN-L2 | The Interview starts once by itself after that, using those notes as guesses to confirm. Anything it changes asks first, since the notes come from mail | MVP |
| CHT-S1 | Answers cite what the turn read, as superscript numbers, with a sources pill in the action bar listing what was cited and what else was read. A citation of anything unread is dropped, titles come from the database, and clicking opens the email or document over the chat | MVP |
| CHT-S2 | Approvals show a compact line built from the tool's actual arguments, with the full content formatted one click away. Only a single quoted file write reads as "Create file"; anything else is labelled a command | MVP |
| CHT-S3 | A wavy divider marks each compaction, with its time and approximate tokens before and after. It stays where it happened | MVP |
| NTF-S1 | A short generated sound for important mail, things needing the person, finished chats and reminders. Master mute, per-type switches and a quick mute. Quiet hours apply | MVP |
| UI-G1 | Frosted glass on Settings, document preview, search and menus, solid when transparency is reduced. Settings opens over the page, and a direct link shows the full page | MVP |
| UI-G2 | Right-click menus share their list with toolbars. Opening an email or document tucks an unpinned chat to an edge aura, which brings it back on hover | MVP |
| SRC-1 | Search palette on Cmd or Ctrl K with instant mail and document results, a full page with filter chips and typed from:, and a filter inside each folder. Documents open straight away in a large preview with arrow keys between them | MVP |
| CHN-1 | User channel with Ask, Suggest and Tell from all agents and sessions, each linked to its source; reply in place, or "Open session" to continue in full | MVP |
| CHN-3 | Asks don't hold up other work: the Mail agent uses its best guess, marks the result provisional, and updates it when answered; a session can pause until answered | MVP |
| CHN-5 | Noise control: similar messages grouped, daily limit, respects quiet hours; only urgent asks raise a notification | MVP |
| CHN-7 | Approval cards also appear in the channel, alongside the top-bar queue | MVP |
| CHN-4 | Offer to remember an answer as a memory, prompt change or rule; applied only if the user agrees | Next |
| CHN-6 | Filter by kind and agent; unanswered asks stay visible until answered or skipped | Next |

## E2. Notifications

| ID | Feature | Pri |
|---|---|---|
| NTF-1 | Important-mail alert: browser notification on the web, small pop-up window in Electron (sender, summary, why urgent, Open / Draft / Snooze) | MVP |
| NTF-2 | Quiet hours | MVP |
| NTF-5 | Notification center: history of everything the app raised, unread count, filter by type, act from the list | MVP |
| NTF-6 | Focus mode and focus batches: holds non-urgent mail and delivers it at set times; urgent mail still gets through | Next |

## E3. Panels

A panel is a saved live view over any data in the app: emails from a person, a thread, a task list, documents on a topic. Panels use no model to display, so they cost no tokens.

```text
┌ Priya's mail ─────┐ ┌ Budget thread ────┐ ┌ My tasks this week ┐
│ filter: sender    │ │ filter: thread    │ │ filter: due date   │
└───────────────────┘ └───────────────────┘ └────────────────────┘
        drag to reorder · resize · add · remove
```

| ID | Feature | Pri |
|---|---|---|
| PNL-1 | Create a panel over emails, threads, tasks, reminders or documents, using filters; shows live results | MVP |
| PNL-3 | Drag to reorder and move, slide to resize, add and remove; layout is remembered | MVP |
| PNL-5 | A few starter panels, which can be changed or removed | MVP |
| PNL-2 | Describe a panel in plain words; the agent turns it into a filter the user can see and edit | Next |
| PNL-4 | "Add to panel" from any item or search result; the agent can suggest a panel | Next |
| PNL-6 | Several boards, such as one per project; panels over more data, including people, sessions and connector resources | Next |
| PNL-8 | Agent-written panels: custom code for graphs and other views, running in the artifact sandbox | Later |

## E4. Search

| ID | Feature | Pri |
|---|---|---|
| SRC-1 | Full-text search over mail and attachment text (SQLite FTS5), with filters: sender, date, category, has attachment, folder | MVP |
| SRC-3 | Meaning search with local text embeddings (ONNX), built in the background, with hybrid keyword and meaning ranking | Next |

## E5. Documents

| ID | Feature | Pri |
|---|---|---|
| DOC-1 | Documents library across uploads, email attachments and what agents made, filtered by where it came from, with a Home folder view: preview, full-page reader, search, open the source message; attachments hide signature images | MVP |
| DOC-5 | Reads PDF, Office (including macro-enabled and old formats, best effort), HWP and HWPX, OpenDocument, RTF, Outlook and mail files, CSV and TSV, notebooks, and source code and text of any kind. Scans and pictures aren't read yet | MVP |
| DOC-2 | Upload by drag and drop: copied to `documents/`, text extracted and indexed, usable by the agent | MVP |
| DOC-4 | User folders and tags for documents, draggable like other folders | MVP |

## E6. Tasks & reminders

| ID | Feature | Pri |
|---|---|---|
| TSK-1 | Tasks created from mail (by agent or user), linked to the source thread; manual tasks, due dates, done / in progress | MVP |
| TSK-4 | Do it for me: a button on any task invokes the agent with that task as context; it returns a draft, a file or the question it needs answered | MVP |
| REM-1 | Reminders: created by the user or proposed by the agent, with date, repeat and snooze, linked to a mail or task | MVP |

## E7. People & notes

| ID | Feature | Pri |
|---|---|---|
| PPL-1 | Contact cards built from mail, VIPs, recent threads and shared files per person | Next |
| PPL-2 | Who knows what: reads titles and phones from signatures and learns from mail who works on what ("who handled the SAP migration?") | Next |
| NOT-1 | Notes: quick note by global hotkey, in markdown; from an email or selection, linked both ways; searchable and usable by the agent | Next |

## E8. Artifacts

| ID | Feature | Pri |
|---|---|---|
| ART-1 | Agent generates artifacts from a session: documents, HTML pages, charts, tables; preview in a side panel; HTML runs in a sandbox with no network or system access | Next |
| ART-3 | Revise by asking the agent or editing directly; version history, compare and restore | Next |
| ART-4 | Export as PDF, Word, HTML or Markdown; share by attaching to an email (with approval) or copying the file | Next |
| ART-6 | Share by link; needs a company-hosted server, since data otherwise stays on the device | Later |

---

# F. Work helpers

## F1. Helpers

| ID | Feature | Pri |
|---|---|---|
| WRK-1 | Commitment tracker: finds promises in mail ("I'll send it by Friday", "we'll confirm Monday"), tracks what the user owes and is owed, drafts nudges, and covers "no reply in 3 days" follow-ups | Next |
| WRK-11 | Repetition finder: notices repeated work across mail and files, estimates the time spent, and offers a playbook or rule | Next |
| WRK-10 | Living project pages: auto-built from mail, documents, people and decisions, and updated as new mail arrives. A view over the one Home, not separate storage | Next |
| WRK-2 | Mail as a table: "all PO numbers, amounts and dates from vendor X last quarter" becomes a spreadsheet, with each row linked to its source | Next |
| WRK-3 | Attachment versions: connects versions of a file across threads, shows the latest and explains what changed | Next |
| WRK-4 | Meeting brief: attendees, related threads and files, open items and the last decision | Next |
| WRK-5 | Weekly status draft from sent mail, finished tasks and meetings, in the user's format | Next |
| WRK-6 | Decision log: decisions from threads with who, when and the source quote | Later |
| WRK-7 | Handover pack for role changes or leave: open threads, key contacts, pending commitments and files, as an editable artifact | Later |
| WRK-8 | Playbooks: a repeated process as a named workflow, such as invoice arrives → extract → save → create task → draft acknowledgement | Later |
| WRK-9 | Language bridge: translates incoming mail and replies in the sender's language, showing both versions before sending | Later |
| WRK-12 | Mini tools: "make me a tracker for these vendor quotes" produces a small working tool from mail data, running in the artifact sandbox | Later |
| WRK-13 | Company brain: shared knowledge across employees; needs a company-hosted server | Later |

## F2. Meetings

| ID | Feature | Pri |
|---|---|---|
| MTG-1 | Meeting recording: off by default and started by the user for each meeting, with a visible indicator. Captures microphone and system audio, not the screen. Local transcription with an ONNX speech model; audio deleted afterwards unless kept | Later |
| MTG-3 | Summary on request: decisions, action items and owners, stored with the transcript and passed through the data guard. Shared with attendees by email after approval; action items become tasks and reminders | Later |

---

# Merged IDs

Old IDs folded into another feature during consolidation.

| Now | Includes |
|---|---|
| AGN-3 | AGT-1, AGN-2 |
| AGN-1 | MDL-2 |
| PMT-1 | AGT-2 |
| PMT-7 | PRC-5 |
| PMT-9 | PMT-8 |
| MEM-1 | AGT-11, MEM-2 |
| MEM-3, PMT-2 | HOM-8 |
| TOL-1 | TOL-4 |
| TOL-2 | HOM-9 |
| TOL-3 | AGT-7 |
| SES-1 | SES-4 |
| SES-2 | SES-3, SES-5 |
| JOB-3 | AGT-10 |
| JOB-4 | NTF-4 |
| JOB-7 | REM-2, TSK-3 |
| APP-9 | APP-4 |
| HOM-1 | HOM-2 |
| ONB-1 | ONB-5 |
| ONB-2 | ONB-3 |
| NAV-4 | NAV-5 |
| SET-5 | APP-5, SET-4 |
| LOG-1 | LOG-2 |
| LOG-4 | APP-6 |
| ACC-1 | ACC-2 |
| ACC-3 | ACC-4 |
| ACC-6 | NAV-3 |
| PRC-1 | PRC-2 |
| PRC-4 | PRC-3 |
| PST-1 | PST-2, PST-3, PST-4 |
| ATT-1 | ATT-5 |
| ATT-2 | ATT-4 |
| ATT-3 | SRC-5 |
| THR-11 | THR-12 |
| SRC-1 | SRC-2 |
| SRC-3 | SRC-4 |
| DOC-1 | DOC-3 |
| FIL-1 | FIL-2 |
| NOT-1 | NOT-2, NOT-3 |
| TSK-1 | TSK-2 |
| MOD-3 | MOD-6 |
| MOD-7 | MOD-8 |
| MDL-3 | MDL-4 |
| SDG-1 | SDG-6 |
| SDG-4 | SDG-5 |
| SDG-2 | SDG-7 |
| BUS-2 | BUS-3 |
| BUS-5 | BUS-6 |
| CHN-1 | CHN-2 |
| ART-1 | ART-2 |
| ART-4 | ART-5 |
| PNL-6 | PNL-7 |
| MTG-1 | MTG-2 |
| MTG-3 | MTG-4, MTG-5 |
| WRK-1 | AGT-9 |
| AGN-9 | WOW-6 |
| PMT-10 | YC-2 |
| JOB-4 | YC-3 |
| TSK-4 | YC-4 |
| WRK-10 | YC-5 |
| WRK-11 | YC-6 |
| WRK-12 | YC-7 |

Rejected: YC-1 Injection shield, Back from leave. Not needed for now: YC-8 Voice.
