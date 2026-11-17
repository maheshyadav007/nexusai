# Schedules and monitors: plan

Written 2026-11-18. Turns Schedules from "run a prompt on a clock" into watchers a team head can rely on: check something on a schedule or when something happens, decide by a clear rule, and tell the right people once.

## Rules that apply throughout

Same as the other plans: no real-model evals without asking; never delete on Google's server; theme tokens and one shared component per job; small steps, each with fake tests, the full check and a commit. Two more:
- **The weak model is not on the hot path.** A check that runs every minute never calls a model. A model is used only to write a summary or judge something fuzzy, and only when the rule says so.
- **Nothing leaves without a yes, once.** The first time a schedule would email someone, the person approves the recipients and the wording. After that it sends on its own until they change it.

## Today

- `Schedule` (`contracts/agent.py`): `every` is once, hour, day or week, at a time, with a prompt and a kind (`prompt`, `daily-prep`, `mail-hourly`, `mail-brief`, `mail-review`). Every run is a model run.
- Triggers react to `mail.received` and `mail.urgent` only.
- MCP servers' tools reach agents (`connectors.agent_tools`); there's no way to call one without a model.
- `send_mail` takes to, cc, subject and body. No attachments.
- The Schedules page is a form and a list, and the person dislikes it.

## What the big assistants already do (the baseline)

Checked 2026-11-18, so nothing basic is missed:
- **ChatGPT (Scheduled):** one-time or recurring tasks, and "monitor for changes" or react to supported events. A Scheduled page to create, review, share and manage them. Results by push, email or both. Runs while the person is offline. Caps on active tasks by plan (3 on Free, up to 15 on Pro and Enterprise). No webhooks, and a task in a project can't read the project's files.
- **Gemini (Scheduled actions):** a prompt at a set time or on repeat, with a page to pause, resume, edit and delete. Up to 10 active on paid plans.
- **Microsoft 365 Copilot (Scheduled prompts):** schedule any prompt from Teams, Outlook or Copilot chat; review them under Tasks › Scheduled; schedules can call agents; hourly, daily, weekly, monthly or yearly; admins govern the feature.
- **Claude:** Routines run saved prompts in the cloud on a schedule; desktop tasks run on the person's computer only while the app is open; managed agents take a cron expression and start a fresh session each run.

What they all share, and what this plan must not miss:
1. **Made by asking**, in plain words, and confirmed before it's saved.
2. **A page to see and manage them:** pause, resume, edit, delete and **run now**.
3. **A history of runs** with what each run produced.
4. **Delivery the person chooses:** a notification, an email, or a message in a chat that collects the results.
5. **Common cadences** (once, hourly, daily, weekdays, weekly, monthly, yearly) and the person's **time zone**, with daylight saving handled.
6. **Limits:** a cap on how many are active, and a cost limit per run.
7. **Agents and tools inside a run:** the run can use the same tools and connectors as a chat.
8. **Watching for changes** and **reacting to events**, not only clocks.

Gaps worth closing that they leave open, or that matter more on a desktop app:
- **Missed runs.** NexusAI runs on the person's computer, like Claude's desktop tasks: if it's closed or asleep, a run is missed. Each schedule says whether to catch up once on start, or skip. The run history shows what was missed.
- **An end:** "for the next 4 weeks", "until 30 Dec", or "5 times".
- **Working days and holidays:** "every working day", skipping weekends and a holiday list.
- **Edit by asking:** "move my Friday report to 6" changes the existing schedule instead of making a new one.
- **The schedule's own failures** are reported once: a run that can't start (no model, no network) shows on the page and in a notification, not silently.
- **Fresh or continuing:** each run starts fresh by default, with an option to carry on in one conversation (already a setting on today's schedules).
- **Duplicate and share** a schedule as a template, which corporate teams use to spread good ones.

## What a team head needs watched

Grouped by what they'd say. Each becomes a ready-made template.

**Systems and services**
1. "Check these MCP servers and endpoints every 5 minutes. If one is down or slower than 2 s, email the on-call list." Health check, status code, latency, a value in the reply.
2. "Tell me when the build on main fails, and when it's fixed." State change, not every failure.
3. "Warn me 14 days before a certificate, domain or licence expires."
4. "If the error count on this dashboard goes over 50, tell the team." A number from an MCP tool or an endpoint, against a threshold.

**Mail and people**
5. "If anyone from my leadership list writes and I haven't replied in 4 working hours, remind me." VIP response time.
6. "If a customer escalation arrives, tell me and the account owner at once." Event-triggered, with a rule on sender or subject.
7. "Every Friday at 4, chase everyone who owes me something." Waiting-on-others follow-ups.
8. "When I've asked someone something and they haven't answered in 3 days, draft a nudge for me to approve."

**Running the team**
9. "Every Friday at 5, write the team's weekly status from this week's mail and send it to my manager." Report, with approval the first time.
10. "Every Monday at 9, list overdue tasks and reviews waiting on me." Personal digest.
11. "Every morning, the deadlines in the next 7 days that came from mail." Deadline radar.
12. "On the 1st of each month, fill the KPI sheet and send it to finance." Joins the form-filling plan (`docs/FORM_FILLING_PLAN.md`).

**Outside world**
13. "Every morning, anything new about 3GPP Release 20 or our competitors." Web search with change detection.
14. "Watch this page and tell me when it changes." A page's text, compared with last time.

**Documents**
15. "When a new file lands in this folder, summarise it and tell me." Folder watch.

## Design

A schedule is five parts, each its own small piece, so a new kind of monitor is one new part, not a new feature.

| Part | What it is | First kinds |
|---|---|---|
| **When** | What starts a run | every N minutes (1 minimum), hourly, daily at a time, weekdays, weekly, monthly on a day, once; an event (new mail matching a rule, a new file, a team task closing) |
| **Check** | What it looks at, without a model | call a web address (status, time taken, body); call an MCP tool with fixed arguments; count mail matching a search; read tasks, reminders or the work board; a web search; a page's text; a folder's new files; or "ask an agent" for the fuzzy ones |
| **Condition** | A rule that says whether to act | down or wrong status; slower than N ms; a value (JSON path or regex) above, below or equal to N; changed since last run; matched anything; N failures in a row; days until a date below N; always (for reports) |
| **Action** | What happens when the condition holds | email a list (from the configured sender); a notification in the app; a message in a chat; a task or reminder; run an agent with a prompt and the check's result; fill and send a file |
| **Policy** | How it behaves over time | alert once, then a cool-down; tell again only when it changes; a "recovered" message; quiet hours, with urgent allowed through; escalate to a second list after N more failures; a daily cap on emails; a token budget for the model parts |

Every run is recorded: when, what the check saw, whether the condition held, what it did, how long, and the cost. A monitor keeps its state: up or down, failures in a row, when it last alerted. That's what stops a broken server sending an email every minute.

### Where it lives

- A `monitors` module in the backend, next to the scheduler, with its own tables: `monitors` (the five parts as JSON, validated by contracts), `monitor_runs` (history, pruned after 30 days) and `monitor_state`.
- The existing scheduler loop starts monitors that are due. Checks run in a small worker pool with timeouts, so a slow endpoint never holds the others up.
- Checks with no model run in-process and cost nothing. "Ask an agent" checks and agent actions go through the normal runtime, so they show in Sessions and the team map.
- Existing schedules (brief, prep, prompt) become monitors with `When` and an "ask an agent" action, so there's one list and one page.

### Making them

- **By asking.** "Monitor these MCP servers every 5 minutes and email ops@… if one fails." Posty, or a new **Monitor** agent, fills the five parts and shows a card: what it will check, the rule, who it will tell, how often. The person approves it, as with any other proposal. A weak model only fills a typed form, which is checked before it's shown.
- **From a template.** The list above, each with only the blanks to fill.
- **By hand.** A form in the same five steps.

### Safety

- Web addresses and MCP calls are made by the app, not the model. The address is shown in the proposal and saved; a run can't change it.
- Secrets for endpoints (a token, a header) go to the operating system's keychain, like MCP tokens.
- What an endpoint, a page or a search returns is untrusted: it's never followed as instructions, and it's wrapped as such when it reaches a model.
- Alert emails go only to the approved list, with an approved template. A change to either asks again.
- A daily cap on emails per monitor and in all, with a notification when it's hit.

### The page

Redesigned with this work, in the style of Sessions and Tasks:
- **Groups:** Needs attention (failing or paused by a cap), Monitors, Reports and briefs, Paused.
- **Each row:** a status dot (live, failing, healthy), the name, its rule in plain words ("every 5 min · alert ops@… if down"), the last result and the next run.
- **Details beside the list:** the five parts, a strip of the last 50 runs (green, amber, red), the run history with what each check saw, and Run now, Pause and Edit.
- "New monitor" opens the templates first.

## Order of work

1. **Model and runner.** Tables, contracts for the five parts, the runner with timeouts, state and history, and the cool-down and recovery rules; cadences up to yearly, working days, an end, the time zone, missed-run catch-up, a cap on active schedules. Fake clock tests: a failing check alerts once, recovers once, escalates after N; a closed app catches up once.
2. **Checks with no model.** Web address, MCP tool call, mail count, tasks and reminders, folder. Fake HTTP and fake MCP in tests.
3. **Actions.** In-app notification, email to an approved list (first send asks), task or reminder, run an agent. The approval for a standing recipient list.
4. **Asking for a monitor.** The proposal card from a chat request, with the form filled by the model and validated.
5. **The page.** List, details with history and each run's output, run now, pause and resume, templates, duplicate, editing; edit by asking from the chat.
6. **Old schedules become monitors**, with a migration and no change in what they do.
7. **Web search and page watch** (shares the web search tool with the form-filling plan).
8. **Real checks, with permission:** a real MCP server and endpoint, alerts to the person's own address on Gmail.

## Decisions for the person

- A **Monitor** agent, or Posty filling monitors itself? (Recommended: Posty proposes, the form is checked by code; no new agent until the volume asks for it.)
- The **shortest interval**: 1 minute, or 5? (Recommended: 1 for web addresses and MCP calls with no model, 15 for anything with a model.)
- **Alerts beyond email** (Teams, Slack, SMS) now or later? (Recommended: later, behind the same Action part.)
