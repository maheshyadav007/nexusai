# To do

Work agreed on but not planned yet. Each item gets a proper plan before it's built. Items are grouped so each group is built once, as a general piece, and every case after it is a small addition rather than new code.

Reviewed 2026-11-25. Removed as done: the compact hand-over in the chat panel (built in `8904a74`) and "Posty sees what the app shows" (built 2026-11-24, `docs/AGENT_SYNC_PLAN.md`; trying it on the real account is under "To try").

## Routines: one model for everything that runs by itself

Noted 2026-11-17, widened 2026-11-25. Schedules, the morning brief, monitors and jobs started by mail are all the same thing: **something starts it, it does some steps, and it tells someone**. Build that once.

- **Starts on:** a time (what Schedules does today), something happening (an email matching a rule or a description, a task coming due, a check failing), or by hand.
- **Steps:** a prompt for an agent, a check that needs no model (planned in `docs/SCHEDULES_AND_MONITORS_PLAN.md`), or filling a form or sheet (`docs/FORM_FILLING_PLAN.md`).
- **Tells:** Today, a notification, an email, later other channels. Each routine keeps its own history, so a failing one doesn't alert every minute.
- **Templates to start from.** The morning brief becomes the default routine, shown as the first template and on by default, not a separate built-in kind of schedule.
- **Mail-triggered jobs**, the case asked for: "when an email like this arrives, do this job". For example, detect a release mail and prepare the checklist, the way the Sharpy screenshots show an update being kept and then run. As there, nothing runs before the person keeps it.
- **Monitors** are a routine whose start is a check (an endpoint or an MCP health check every N minutes, a condition, an alert to a list of addresses). The plan for them is written and not built.

## How agents read: paging and limits

Noted 2026-11-25. A tool's output is cut at 20,000 characters (`max_tool_output_chars`) and the model is told "[Cut off: N characters in all.]", but `read_file` and `read_document` have no way to ask for the rest. A run tried nine times with the same call to get a whole file.

- One way to page for every reading tool: an offset or page argument, and a cut-off note that says the exact call to read the next part, as `read_thread` already does with `skip_newest`.
- A test that every tool which can be cut off can page.

## Nothing internal on screen

Noted 2026-11-25. Answers no longer show keys (built 2026-11-24), but a few places still do:
- The thinking trace's chips show raw values: `read_document` shows its key (`m:12:2`); deleting tasks, reminders, schedules and panels shows bare ids (`ThinkingTrace.tsx`).
- Approval summaries: "Read document m:12:2", "Change tasks 3, 4", "Read conversation 225" (`tools.py`, `work_tools.py`).

General fix: one helper that names an object for the person by its title from the database, used by chips, approval summaries and anything else that shows an object. Then a test that no shown text matches a raw key.

## Lists and pages

Noted 2026-11-24 and 2026-11-25. Shared behaviour first, so every list gets it:
- **Waiting pages show they're working.** A shared loading state, a spinner and a line on what it's doing, for any page waiting on server work. Sort senders is the first. No page should look frozen.
- **Double-click opens.** On any list row (mail, matters, tasks, documents), double-click opens it in full; a single click selects. One behaviour in the shared list row.
- **Grouped by state, the same way everywhere.** Waiting on you, waiting on others, worth knowing and done, in that order:
  - **Week** mixes every state in one lane today; it should separate them.
  - **Tasks** should show suggested ones (waiting to be kept) apart from kept ones, and work with a due date apart from the rest, so the person sees at a glance what's dated. Reminders the same.

Page by page:
- **Notifications:** a "Clear all" button that clears every notification at once.
- **Documents:** it lists calendar invites (`.ics`) from mail as documents. They should be left out, or shown under the meeting they're for.
- **Matters tab, zip-through:** the list and the matter each scroll on their own, ↑↓ moves through matters and opens each one, and a decision bar pinned at the top of the matter offers Keep (keep its suggestions) and Not for me (decline them and mark it done), then opens the next. Proposed 2026-11-25 as a sketch; needs a visual mockup and approval before building.
- **Q&A card** (the `ask_user` question in the chat): improve how it looks while it's waiting for an answer and after it's answered.

## Learn from Littlebird

Noted 2026-11-25. Research only, to bring back what fits:
- How its onboarding handles mentions casually, compared with our Reach step.
- How it structures tools, skills and prompts, and how it decides which tools an agent is shown.

## Vectorize only mail the AI reads

Noted 2026-11-21. The semantic index should embed only email that reaches the Mail agent.

Done in part, 2026-11-21: setup sorts right after mail is connected, and the index takes no mail until sorting is done or skipped. After that it leaves out folders the AI doesn't read (`KEPT_MAIL` in `modules/semantic/module.py`). Left to check: mail the header rules keep from the AI that isn't in such a folder, and Homes that set up before sorting existed, which still index everything they hold.

## To try

- **Posty sees what the app shows** (built 2026-11-24): ask "What needs me today?" and "what's been completed" on the real account with the real model, and check that the answers cite matters and tasks and that nothing done shows as overdue. Ask first, since it spends the ChatGPT allowance.
