# Schedules and monitors: plan

Written 2026-11-18, revised the same day after a second round of research. Turns Schedules from "run a prompt on a clock" into watchers a team head can rely on: check something on a schedule or when something happens, decide by a clear rule, and tell the right people once.

The revision changes three things. It **builds on the scheduler we have** instead of starting a second system. It adds a **proper alert life cycle**, so a monitor doesn't flap, spam or cry wolf when the laptop is asleep or offline. And it makes **testing before saving** part of the flow.

## Rules that apply throughout

Same as the other plans: no real-model evals without asking; never delete on Google's server; theme tokens and one shared component per job; small steps, each with fake tests, the full check and a commit. Three more:
- **The weak model is not on the hot path.** A check that runs every minute never calls a model. A model fills the proposal form, writes a summary or judges something fuzzy, and only when the rule says so.
- **Nothing leaves without a yes, once.** The first time a schedule would email someone, the person approves the recipients and the wording. After that it sends on its own until they change either.
- **Can't check is not down.** If the app is asleep, offline or can't reach anything, that is recorded as a missed or unknown run. It's never reported as the target failing.

## Today (what we build on)

- `scheduler.py` already has a single timer that sleeps at most 5 minutes and re-reads the clock, so a closed laptop catches up on waking. It handles DST, uses a time zone per schedule and runs a missed schedule **once** on waking, not once for every missed slot.
- `trigger_runs` is already a durable run queue: pending → running → done, `UNIQUE (trigger, event)` so a run is never queued twice, manual runs, and a reset to pending after a crash.
- `Schedule` (`contracts/agent.py`): `every` is once, hour, day or week, at a time, with a prompt and a kind (`prompt`, `daily-prep`, `mail-hourly`, `mail-brief`, `mail-review`). Every run is a model run.
- The overdue and follow-up jobs are already model-free checks that "tell once" (`overdue_notified_at`, `followup_notified`). Monitors generalise that pattern.
- Triggers react to `mail.received` and `mail.urgent` only. `send_mail` has no attachments. The Schedules page is a form and a list, and the person dislikes it.

**Decision:** no separate `monitors` module. A monitor is a schedule with a check. The `schedules` table gains nullable `check`, `condition`, `actions` and `policy` columns (JSON, validated by contracts), `trigger_runs` gains the run's result, and there's one small `schedule_state` table. That gives one queue, one list, one page, and nothing old to migrate: existing schedules simply have no check.

## What the big assistants do (the baseline)

Checked 2026-11-18:
- **ChatGPT Scheduled (June 2026, replaced Pulse):** a Scheduled page to create, pause, edit and delete tasks. Monitoring tasks **remember earlier results**, so they can tell what's new, and **use judgment to alert only when something matters**. Runs at most hourly. Caps on active tasks: 3 on Free up to 15 on Pro and Enterprise. Push, email or both.
- **Claude:** Routines run in the cloud. Desktop scheduled tasks run only while the app is open. **Run now** is how people test before enabling a task. The run history shows **skipped runs and why** ("computer asleep", "previous run still going"), and any past run opens as a full session.
- **Gemini scheduled actions** and **Microsoft 365 Copilot scheduled prompts:** a prompt on a clock with a page to pause, resume, edit and delete. Copilot goes up to yearly, can call agents and is governed by admins.

Borrowed from proper monitoring tools, because this is where AI assistants are weakest:
- **Grafana alerting:** states Normal → Pending → Firing → Recovering, with a *pending period* (failures needed before alerting) and *keep firing for* (successes needed before "recovered"). It treats *Error* and *No data* separately from the condition itself.
- **Alertmanager and PagerDuty:** a dedup key per incident, repeat reminders only on a slow interval, and **Acknowledge**, which silences an incident until it recovers.
- **Healthchecks.io:** a "dead man's switch" that alerts when the watcher itself has gone quiet.

Must-haves from all of them: made by asking and confirmed; a page to pause, resume, edit, delete and run now; a history of runs, including skipped ones and why; delivery the person chooses; common cadences in the person's time zone; a cap on active schedules and a cost limit per run; tools and connectors inside a run; watching for changes and reacting to events.

## What a team head needs watched

These become the templates. ★ marks the first release.

**Systems and services**
1. ★ "Check these MCP servers and endpoints every 5 minutes. If one is down or slower than 2 s, email the on-call list."
2. "Tell me when the build on main fails, and when it's fixed." This is a state change, not every failure. It needs an MCP or CI connector.
3. ★ "Warn me 14 days before a certificate expires." This comes for free from the web check. Domains and licences are a date in a sheet, so they come later.
4. ★ "If the error count on this dashboard goes over 50, tell the team." A number from an MCP tool or an endpoint, compared with a threshold.

**Mail and people**
5. ★ "If anyone on my leadership list writes and I haven't replied in 4 working hours, remind me."
6. ★ "If a customer escalation arrives, tell me and the account owner at once." Triggered by an event, with a rule on sender or subject.
7. ★ "Every Friday at 4, chase everyone who owes me something."
8. "When I've asked someone something and they haven't answered in 3 days, draft a nudge for me to approve." This extends today's follow-up job.

**Running the team**
9. ★ "Every Friday at 5, write the team's weekly status from this week's mail and send it to my manager." Approved the first time.
10. ★ "Every Monday at 9, list overdue tasks and reviews waiting on me."
11. ★ "Every morning, the deadlines in the next 7 days that came from mail."
12. "On the 1st of each month, fill the KPI sheet and send it to finance." Joins `docs/FORM_FILLING_PLAN.md`.

**Outside world and documents**
13. "Every morning, anything new about 3GPP Release 20 or our competitors."
14. "Watch this page and tell me when it changes."
15. "When a new file lands in this folder, summarise it and tell me."

## Design

A monitor is a schedule with four more parts. Each part is a small registry, so a new kind of check is one function and one contract, not a new feature.

| Part | First release | Later |
|---|---|---|
| **When** | every N minutes, hourly, daily at a time, working days, chosen weekdays, monthly on a day (31 means the last day), yearly, once; an end ("until 30 Dec", "5 times"); events: new mail matching a rule | a holiday list, a new file in a folder, a team task closing |
| **Check** (no model) | a web address (status, time taken, a value in the body, days until the certificate expires); an MCP tool with fixed arguments; a count of mail matching a search; tasks and reminders | a web search, a page's text, a folder's new files |
| **Condition** | fails or returns the wrong status; slower than N ms; a value (a JSON path) above, below or equal to N; contains or lacks some text; changed since last run; days left below N; always (for reports) | "ask an agent: does this matter?" |
| **Actions** | a notification in the app; a message in the schedule's own chat thread; email to an approved list; run an agent with the result | a task or reminder; fill and send a file; Teams or Slack |
| **Policy** | (defaults below) | escalate to a second list |

Defaults are set so the person rarely touches Policy:
- **Confirm before alerting:** 2 failures in a row (1 for checks every hour or less often).
- **Confirm before "recovered":** 2 passes in a row.
- **While it's still failing:** a reminder every 4 hours by default, which can be turned off. Never once a minute.
- **Quiet hours** follow the person's existing setting. Urgent alerts can be let through, per monitor.
- **A daily cap** on emails per monitor (default 10) and for all monitors (default 50). When a cap is hit, one notification says so.

### The alert life cycle

Each monitor has one state, kept in `schedule_state`:

```
 OK ──fail──▶ CHECKING ──fail×N──▶ ALERTING ──pass──▶ RECOVERING ──pass×N──▶ OK
  ▲              │pass                │ "Got it"           │fail
  └──────────────┘                    ▼                    └──▶ ALERTING (no new alert)
                                  ACKNOWLEDGED ──pass×N──▶ OK (one "recovered" note)

 Any state ──can't run the check──▶ same state, run marked "couldn't check"
```

- An alert opens an **incident** with an id. Every message about it carries that id, so it never sends twice, even after a crash and retry.
- **"Got it"** on the alert (in the chat, the notification or the page) silences reminders until it recovers. **Mute for 1 hour / until tomorrow** sits beside it.
- **Couldn't check:** before any web or MCP failure counts, the runner confirms the app itself is online by checking a second, known address. If the app is offline, asleep or the run was skipped, the run is recorded as *couldn't check* and the state doesn't move. After 3 hours with no successful check, a single "I haven't been able to check X since 10:40" note is sent.
- **Flapping:** if a monitor changes state more than 4 times in an hour, it holds ALERTING and says "unstable" instead of sending each change.

### Running checks safely

- A small worker pool (4) with a timeout per check (10 s by default). Bodies are capped at 1 MB. Redirects to another host are shown in the proposal, not followed silently.
- **No overlap:** if the previous run of a monitor is still going, the new one is recorded as *skipped: still running*.
- Web addresses and MCP calls are made by the app, never by the model. The address is fixed in the approved proposal, and a run can't change it.
- Endpoint secrets (a token, a header) go to the operating system's keychain, as MCP tokens do.
- Whatever an endpoint, page or search returns is untrusted. It's never followed as instructions, and it's wrapped as such when it reaches a model.
- Email goes through an outbox with retries. If sending fails, the in-app alert still lands and says the email didn't go.
- **The watcher watches itself:** the scheduler writes a heartbeat. On start, if the heartbeat is older than the next due run, the app says once: "NexusAI was closed from 18:02 to 09:15. 3 checks were missed. All fine now", or names what isn't.

### Change detection, so it isn't noisy

For "changed since last run" and page watches:
- Keep the last snapshot. Compare the *meaningful* text: strip the HTML, then numbers that look like times or dates, and whitespace. Show the actual difference in the alert.
- An optional **"only if it matters"** switch, like ChatGPT's judgment, sends the difference (not the page) to the model with the person's stated interest. The model answers yes or no with a one-line reason, and the reason is shown in the alert so the person can see why.
- Run at most hourly when a model is involved.

## The flow and the UX

NexusAI is chat-first, so a monitor is made, tested, followed and edited in the chat. The page is for looking over all of them.

**1. Ask.** "Monitor our three MCP servers every 5 minutes and email ops@… if one goes down."

**2. Posty proposes a card.** Posty is the only one filling the typed form, and code checks it before the card appears:

```
┌──────────────────────────────────────────────────────────────┐
│ Watch 3 MCP servers                                          │
│ Every 5 min · alert after 2 failures · email ops@samsung…    │
│                                                              │
│ Tested just now                                              │
│   ● search-mcp    200 · 180 ms                               │
│   ● files-mcp     200 · 240 ms                               │
│   ● build-mcp     timed out after 10 s  ← would alert        │
│                                                              │
│ Email preview ›      Details ›                               │
│                                                              │
│ [ Turn on ]   [ Change ]   [ Not now ]                       │
└──────────────────────────────────────────────────────────────┘
```

- The rule is written in one plain sentence. Settings that were left at their defaults aren't listed.
- **Tested just now** runs the check once, before saving, with no actions. This catches a wrong address or token at the moment the person is looking.
- **Email preview** shows the exact message and the recipients. Turning the monitor on approves both.
- If Posty couldn't fill something ("which list is on-call?"), it asks one question. It never guesses an address.

**3. One thread per monitor.** Alerts, recoveries and report results post into that monitor's thread in the chat, so the history reads like a conversation. The notification opens that thread. Each alert has **Got it**, **Mute**, **Run now** and **Edit**.

**4. Edit by asking.** "Move my Friday report to 6" or "add Priya to the server alert" changes the existing monitor. Posty shows only what changed ("Friday 17:00 → 18:00"), and a change to recipients asks again.

**5. The page** (in the style of Sessions and Tasks):
- **Groups:** Needs attention (alerting, couldn't check, capped), Monitors, Reports and briefs, Paused.
- **Each row:** a status dot, the name, the rule in plain words ("every 5 min · alert ops@… if down"), the last result in words ("OK 2 min ago", "Down for 14 min") and the next run.
- **Details beside the list:** a strip of the last 50 runs (passed, failed, couldn't check, skipped), each opening what the check saw; the current incident; Run now, Pause, Duplicate and Edit.
- "New" opens the templates first, as cards, each with only its blanks to fill. Editing by hand is the same card in edit mode, not a separate long form.
- The empty page shows 4 starter templates and the line "Or just ask in the chat".

## Limits

- 25 active monitors (configurable). The cap is shown on the page before it's reached.
- Shortest interval: 1 minute for checks with no model, 60 minutes for anything with a model.
- A token budget per run for the model parts (the existing `token_limit`).
- Run history is kept for 30 days, and incidents for 90.

## Order of work

Each step is shippable and tested with a fake clock, fake HTTP and fake MCP.

1. **Cadences.** Every N minutes, working days, chosen weekdays, monthly (with the last day), yearly, an end and a count, all in `next_run_after`. Property tests across DST changes and month ends, with 10,000 random schedules and no run in the past or skipped.
2. **Checks and the life cycle.** The new columns, `schedule_state`, the web and MCP checks, conditions, the state machine with incidents, couldn't-check and no overlap. Fake-clock tests: a down server alerts once; it recovers once; a flapping server says "unstable"; an offline laptop sends no alert; a crash mid-send doesn't send twice.
3. **Actions.** In-app notification, a message in the monitor's thread, email through the outbox to an approved list, Got it and Mute, and the daily caps.
4. **Asking for a monitor.** Posty's typed form, validation, Tested just now, the proposal card with the email preview, and edit by asking.
5. **The page.** Groups, rows, details with the run strip, Run now, Pause, Duplicate, templates and the empty state.
6. **Mail checks and events.** Mail-count checks, VIP response time in working hours, escalation by sender or subject (templates 5–7, 9–11).
7. **The heartbeat** and the "while you were away" note.
8. **Change detection and web search.** Page watch, news, and "only if it matters". This shares the web search tool with the form-filling plan.
9. **Real checks, with permission:** a real MCP server and endpoint, with alerts to the person's own Gmail address.

## Decisions for the person

- **Who proposes monitors:** Posty, with code checking the form, and no new Monitor agent until volume calls for one? (Recommended: yes.)
- **Shortest interval:** 1 minute with no model and 60 with one? (Recommended: yes.)
- **Alerts beyond email** (Teams, Slack, SMS): later, behind the same Actions part? (Recommended: later.)
