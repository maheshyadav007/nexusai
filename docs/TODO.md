# To do

Work agreed on but not planned yet. Each item gets a proper plan before it's built.

## Vectorize only mail the AI reads

Noted 2026-11-21. Today the semantic index embeds every email, before the rules sort anything, so newsletters, tool notices and everything else kept from the AI gets embedded too. That's wrong: only email that passes through the AI (what the rule engine lets reach the Mail agent) should be vectorized. Just a note for now; to be planned.

## Monitoring schedules

Planned in full in `docs/SCHEDULES_AND_MONITORS_PLAN.md`. Filling forms and spreadsheets from mail is planned in `docs/FORM_FILLING_PLAN.md`.

Noted 2026-11-17. The Schedules page today only runs a prompt on a clock. The person wants schedules that watch things and alert, for example:

> Monitor these MCP servers every hour (or every minute). If a health check fails, or a condition I set isn't met, email these addresses: …

What it needs, to be planned:
- **Checks the schedule can run on its own:** call an endpoint or an MCP server's health check, then judge the result against a condition (status, response time, a value in the reply).
- **Alerts:** send an email through the already-configured sender to a list of addresses; later other channels.
- **Intervals:** minutely, hourly, daily, or a cron-like rule, with limits so a minutely check stays cheap: no model call unless the condition needs one.
- **Its own history:** each run's result, failures in a row, and when an alert went out, so a broken server doesn't send an email every minute.
- **Built to extend:** monitoring is the first of a family (watch a page, watch a folder, watch a metric), so the check, the condition and the alert are separate, reusable parts.
- **A Schedules page redesign** that fits these, done with this work rather than before it.

## Chat panel: compact hand-over

Design locked 2026-11-17: https://claude.ai/artifact/1vrr8wWijF8pFGMUYdETgv (the bottom artboard, "The full chat panel: today and proposed"). To build:
- One line per hand-over (live dot, agent, task, state), details on click, using a shared `LiveDot` primitive.
- The live "Thought" line shows the step and elapsed time.
- "Organizer is on 2 tasks" above the message box while hand-overs run.
- The giver's wake-up shows as a divider ("Organizer reported · 9:42 PM"), not as a message from the person.
