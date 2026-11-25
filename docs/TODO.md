# To do

Work agreed on but not planned yet. Each item gets a proper plan before it's built.

This file is written so someone new to the project, or us after a long break, can pick up any item without the conversation it came from. Every item says the same things in the same order:

- **What:** the change, in a sentence or two.
- **Why:** where it came from and what went wrong without it.
- **Today:** how the app behaves now, and the files involved.
- **Approach:** the idea agreed so far. It's a direction, not a plan.
- **Open questions:** what to decide before building.
- **Done when:** how we'll know it's finished.

Items are grouped so each group is built once, as a general piece, and every later case is a small addition rather than new code. That's the rule for this list: **no one-off fixes where a general one fits.**

House rules that apply to every item: show a mockup and get approval before any UI change; no real-model evals without asking first (they spend the ChatGPT allowance); test on the real Gmail account before calling a mail feature done; nothing hard-coded in the UI (theme files and the shared primitives in `ui/primitives`).

Last reviewed 2026-11-25. Removed as done that day: the compact hand-over in the chat panel (built in `8904a74`) and "Posty sees what the app shows" (built 2026-11-24, see `docs/AGENT_SYNC_PLAN.md`; trying it on the real account is under "To try").

---

## 1. Routines: one model for everything that runs by itself

**What:** Schedules, the morning brief, monitors and jobs started by an email become one feature, "routines". A routine is: *something starts it → it does some steps → it tells someone.* Build that once; every kind of automation after it is a new starter, step or channel, not a new system.

**Why:** Noted 2026-11-17 as "monitoring schedules", widened 2026-11-25. Three asks turned out to be the same shape:
- Monitors: "check these MCP servers every hour; if a health check fails, email these addresses."
- The morning brief, which today is a special built-in kind of schedule with its own code path.
- Mail-triggered jobs: "when an email like this arrives, do this job." The example shared was Sharpy (getsharpy.com): it notices a repeated question ("what moved on Kite since Friday?" asked three mornings running), offers a routine ("Kite update, every weekday at 9:00, reads Linear and Slack, posts in #kite-health, saves about 40 minutes a week") with **Keep it / No thanks**, says "Nothing runs before you keep it", then shows each run as a card with its steps ticked.

Building each separately would give three schedulers, three histories and three settings pages.

**Today:**
- Schedules run a prompt on a clock: `modules/agent/scheduler.py` (the `schedules` table; cadences daily, weekdays, weekly, monthly, yearly, with an end date) and `modules/agent/triggers.py` (dispatches each run as an agent turn).
- The brief is a schedule with `kind = 'mail-brief'` (`BRIEF_KIND` in `scheduler.py`), inserted by `BUILT_IN_MIGRATION` as "Morning brief, daily 08:30". `triggers.py` gives it `mail_agent.brief_task` as its input. The daily-prep agent writes it with `update_brief`.
- Events that could start things already exist on the event bus (`mail.triaged`, `tasks.changed` and so on), but nothing lets the person attach a job to one.
- The Schedules page (`frontend/ui/features/agent/SchedulesScreen.tsx`) has templates to start from, such as "Deadlines this week".
- Monitors are planned in full in `docs/SCHEDULES_AND_MONITORS_PLAN.md` (checks without a model, conditions, an alert life cycle that doesn't flap, test before saving) and not built. Filling forms and sheets from mail is planned in `docs/FORM_FILLING_PLAN.md`.

**Approach:**
- **Starters:** a time (as now); an event, such as an email matching a rule or a plain-words description, a task coming due, or a check failing; or by hand.
- **Steps:** an agent prompt; a check that needs no model (from the monitors plan); fill a form or sheet (from the form plan). Later: call a connector's tool.
- **Tells:** Today, a notification, an email to a list; later Telegram and WhatsApp (see the Posty harness work).
- **History per routine:** each run's result, failures in a row, and when it last alerted, so a broken check doesn't email every minute.
- **Templates:** the morning brief becomes the first template and the default routine, on by default, instead of a built-in kind with special code. "Deadlines this week" and the monitor examples become templates too.
- **Offered, not imposed:** like Sharpy, Posty can notice a repeated ask and offer a routine. Nothing runs until the person keeps it.

**Open questions:** how a mail starter is described (a fixed rule, a plain-words description judged by the mail agent, or both); whether a mail-started job runs inside the triage run or as its own run (its own run is safer and easier to see); how the brief's special parts (its sections, citations and Today card) fit a general routine without losing anything.

**Done when:** the brief runs as a routine made from a template with no special-case code; a mail-started routine runs on a test mailbox when a matching email arrives; a monitor routine runs without a model and alerts once per failure; one page lists every routine with its last result.

## 2. How agents read: paging and limits

**What:** Every tool that reads something long can return it in parts, and says exactly how to get the next part.

**Why:** Noted 2026-11-25. In a real run the agent could only get part of a file, so it called the same tool nine times with the same arguments, getting the same first part each time. That wastes tokens, and with a weak model it never recovers.

**Today:**
- Every tool's output is cut at 20,000 characters (`max_tool_output_chars` in `kernel/defaults.toml`, applied in `_guarded` in `modules/agent/tools.py`). The model is told "[Cut off: N characters in all.]".
- `read_file` (schema `_Read`: just `path`) and `read_document` (schema `_ReadDocument`: just `key`) take no offset or page, so there's no way to ask for the rest.
- `read_thread` already does it right: it pages with `skip_newest` and its cut-off note says the exact value to pass next.

**Approach:**
- One shared way to page for every reading tool: an `offset` (or `page`) argument, and a cut-off note that gives the exact next call, such as "Showing characters 0–20,000 of 84,000. read_document with offset=20000 reads the next part."
- Apply it to `read_file`, `read_document`, `read_database` and anything else that can be cut off.
- A test that walks every tool that can be cut off and checks it can page.
- As a safety net: when a tool is called again with identical arguments in one run, answer "Same as before; use offset to read further" instead of repeating the output. Check first whether the existing repeated-refusal logic in `tools.py` (`_after_refusal`) can be extended to cover it.

**Open questions:** characters or lines for text files (lines read better for code, characters fit documents); whether documents should page by their own pages (`#p3`), which citations already use.

**Done when:** a 100,000-character document can be read to the end in a few calls in a scripted test, and no reading tool cuts output without saying how to continue.

## 3. Nothing internal on screen

**What:** The person never sees an internal key or bare id, anywhere. Everything is named by its title.

**Why:** Noted 2026-11-25. Raw keys like `m:12:2` and ids like "task 3" mean nothing to the person and make the app look broken. On 2026-11-24, answers were fixed: a key written bare becomes a citation or is dropped (`citations.RAW` in `modules/agent/citations.py`). Other places still show keys.

**Today**, still showing raw values:
- The thinking trace's chips (`frontend/ui/features/assistant/ThinkingTrace.tsx`, the `TOOL_SHOWN` table): `read_document` shows its `key` (`m:12:2`); `update_documents` and `delete_documents` show `keys`; `delete_tasks`, `delete_reminders`, `run_schedule`, `remove_schedules` and `remove_panels` show bare ids.
- Approval summaries, the text on approval cards and in Activity: "Read document m:12:2" (`read_document` in `tools.py`), "Read conversation 225" (`read_thread`), "Change tasks 3, 4" (`update_tasks` in `work_tools.py`), "Change reminders …".

**Approach:**
- One helper on the backend that names any object for the person, by its address (`kinds.py`) and with its title from the database: "Read “Q3 budget.xlsx”", "Change “Send the RCA” and “Book flights”". It's the same lookup citations already use (`sources.describe`).
- Approval summaries use it. The trace's chips show titles: either the backend adds a display name to each tool call, or the chip falls back to the tool's label alone.
- A test that no text shown to the person (summaries, chips, notifications, toasts) matches a raw key pattern.

**Open questions:** whether chips get titles from the backend (correct, costs a lookup) or simply drop ids (cheaper, shows less).

**Done when:** the key-pattern test passes over every tool's summary and chip.

## 4. Lists and pages

Shared behaviour first, so every list gets it. Then the page-by-page fixes.

### 4a. Waiting pages show they're working

**What:** Any page waiting on server work shows a spinner and a line on what it's doing.

**Why:** Noted 2026-11-25. Sort senders (`frontend/ui/features/mail/SortScreen.tsx`) can take a while to group a large mailbox, and the page looks frozen meanwhile.

**Approach:** one shared waiting state in `ui/primitives` (spinner, a line such as "Grouping 4,812 emails by sender…", progress when known), used by Sort first and then by every page that loads server work. If the work runs longer than a few seconds, say what it's doing.

**Done when:** Sort and every other slow page show the shared waiting state, and none shows a blank or frozen screen.

### 4b. Grouped by state, the same way everywhere

**What:** Lists of work are grouped the same way across the app. Matters: waiting on you, waiting on others, worth knowing, done. Tasks and reminders: suggested apart from kept, and dated apart from undated.

**Why:** Noted 2026-11-25.
- **Week** (`frontend/ui/features/today/matters/WeekTab.tsx`) puts every matter in one set of lanes, so done, waiting on you and waiting on others are mixed and the week can't be read at a glance.
- **Tasks** (`frontend/ui/features/planner/TasksScreen.tsx`) isn't clean: suggestions (proposed by the AI, waiting to be kept) sit among kept tasks, and tasks with a due date aren't apart from the rest, so the person can't see straight away what's dated. **Reminders** (`RemindersScreen.tsx`) has the same problem.

**Approach:** one grouping for the app, using the matter states in `contracts/agent.py` (`MatterState`) and the `proposed` flag on tasks and reminders. Week shows a group (or lane colour) per state with done last. Tasks shows "Suggested, waiting for you" first, then "Due" (by date), then "No date", with done folded at the bottom as now. Reminders the same.

**Done when:** Week, Tasks and Reminders show the same grouping and order, approved from a mockup.

### 4c. Open Posty by double-tapping a key

**What:** Double-tapping **Ctrl** (Windows) or **Option** (Mac) opens Posty's quick ask from anywhere on the computer, the way Spotlight-style tools work.

**Why:** Noted 2026-11-25. The current chord, Control+Alt+Space, is awkward to press and easy to forget. A double tap is quick and memorable.

**Today:** `desktop/quick-ask.cjs` registers the chord with Electron's `globalShortcut` (default `shortcut: 'Control+Alt+Space'`, changeable in settings; a chord that's taken is refused). `globalShortcut` only accepts combinations with a main key, not a modifier on its own, so a double tap can't be done with it.

**Approach:**
- A system-wide key listener in the desktop app, from a native module such as `uiohook-napi`, that watches for the modifier pressed and released twice within about 300 ms with no other key in between.
- Keep the chord as a fallback and as a setting ("Open Posty with: double-tap Ctrl / Control+Alt+Space / off").
- macOS: listening to keys system-wide needs Accessibility permission. Onboarding must explain why and link to System Settings; without it, fall back to the chord quietly.
- Windows: works without permission, but antivirus can flag global key hooks, so check with the signed build.
- Ignore double taps that are part of typing or another shortcut (any other key in between cancels it).

**Open questions:** which native module builds cleanly in our Windows CI (`.github/workflows/windows-desktop.yml`) and signs with the app; whether Linux needs it.

**Done when:** a double tap opens quick ask on Windows and Mac in the built desktop app, typing never triggers it, and the chord still works.

### 4d. Page by page

- **Notifications: Clear all.** Noted 2026-11-24. The notification centre (`frontend/ui/shell/NotificationCenter.tsx`) only clears one notification at a time; the backend has `notifications.list` and `notifications.markRead`. Add a "Clear all" that clears every notification in one step, with undo. Done when one click empties the list and undo brings it back.
- **Documents: calendar invites listed as documents.** Noted 2026-11-25. The Documents page shows every `.ics` invite that came with an email, because attachments of kind `calendar` count as documents (`EMAIL_KINDS = ("attachment", "calendar", "risky")` in `modules/documents/module.py`). Invites aren't documents the person keeps; they clutter the list. Leave `calendar` out of the Documents list, or show an invite under the meeting or email it came with. The agent's tools may still read them. Done when Documents shows no `.ics` files and the agent can still read an invite from its email.
- **Matters tab: zip through and decide.** Noted 2026-11-25, after the Sharpy cards. On a big screen we don't need cards; make the existing Matters tab (`frontend/ui/features/today/matters/MattersTab.tsx`) fast to go through. The list and the matter each scroll on their own; ↑↓ moves through matters and opens each one at once; a decision bar pinned at the top of the matter (it never scrolls away) shows one line of what Posty suggests, with **Keep (K)**, which keeps its suggestions as the person's work, and **Not for me (X)**, which declines them and marks the matter done. After either, the next matter opens, with Undo in a toast. A matter with no suggestions shows only Done and Next. It uses existing actions (accept and decline for suggestions, `matters.done`, undo). Sketched in chat on 2026-11-25; needs a visual mockup and approval before building. Open: should "Not for me" also offer "stop reading this sender"? The suggestion was no at first.
- **Q&A card.** Noted 2026-11-25. When Posty asks something with `ask_user`, the chat shows a question card (`frontend/ui/features/assistant/Cards.tsx`, `ChatView.tsx`). Improve it while it's waiting (clear options, a free answer, what it's for) and after it's answered (collapse to the question and the answer chosen, not the full card). Needs a mockup.

### 4e. Installing an update shows in the status bar

**What:** While a new version downloads, installs and starts for the first time, the app says so: a progress bar where the progress is known, and at least a line in the status bar at the top ("Installing version 0.9.3…") where it isn't.

**Why:** Noted 2026-11-25. Installing a new version is silent. Nothing appears in the status bar at the top, so the person can't tell whether the app is updating, stuck or broken. The same happens when a new version first starts: it may back up the whole Home (about 2 GB on the real account) before the database upgrade, and the app shows nothing meanwhile.

**Today:**
- The desktop app downloads and installs with `electron-updater` in `desktop/main.cjs`. `updateState` holds `state` (checking, available, downloading, error…) and `percent`. Progress shows only in the taskbar or Dock icon (`window.setProgressBar`) and in the app menu's update item ("Downloading update: 42%"). After the download, `installBeside` installs next to the running version, then `markReady`.
- The page reads that state through `window.nexusDesktop` (`frontend/ui/client/desktop.ts`, query `nexus:status`). Only Settings › About & Updates shows it (`frontend/ui/features/settings/DesktopUpdates.tsx`).
- The status bar at the top is `frontend/ui/shell/ActivityIsland.tsx`. It shows running agent work, or "Nothing running" (`activity.idle`), and knows nothing about updates.
- On the first start of a new version, the backend backs up the Home when database migrations are pending (`backups.create(home, "upgrade", …)` in `backend/src/nexusai/api/app.py`), then runs them. Requests can fail meanwhile. While testing on 2026-11-25, the health check answered "Internal Server Error" for a few seconds.
- The desktop's start-up window (`desktop/loading.html`) shows a line per stage (`startupStage(…)`), but nothing for the backup or the upgrade.

**Approach:** one "app update" state that the status bar shows like any other running work: downloading with a percentage, installing, ready to restart (with a Restart button), and on the next start "Backing up and upgrading your data…". Use a progress bar where a percentage is known (the download; the backup if it can report one). The start-up window gets the same lines for the backup and the upgrade. In the browser version, where there's no installer, only the start-up part applies.

**Open questions:** can the backup report progress (bytes copied out of the total), or only a line? Should "ready to restart" ask once, or wait in the status bar until the person chooses?

**Done when:** from clicking Update to the new version's first screen, the person can always see what the app is doing. Checked with a real update from one version to the next, on a Home large enough that the backup takes noticeable time. Approved from a mockup first.

## 5. Learn from Littlebird

**What:** Study the Littlebird app (installed on this Mac) for ideas we can reuse. Research only; nothing is copied, and anything adopted goes through our own plan.

**Why:** Noted 2026-11-25. Two things it seemed to do well:
- **Mentions in onboarding:** it handles "who you are, and the names people call you" casually and quickly. Compare with our Reach step in Sort (one list of the person's and their teams' names, defaults full, first and @-name; built 2026-11-24).
- **How its agent is built:** how it structures tools, skills and prompts, and how it decides which tools the model is shown at each step. Ours: `modules/agent/tools.py` (tool sets per agent, `LEAD_SHOWN`, `find_tools` for the rest), `skills.py`, `prompts/`.

**Approach:** use Littlebird for a session and write down how onboarding asks about names, how tools and skills are presented, and how much prompt it sends (where that's visible). Write a short note in `docs/reference/` comparing it with ours, with what's worth taking.

**Done when:** the note exists, and any idea worth taking has its own item here.

## 6. Vectorize only mail the AI reads

**What:** The semantic index (search by meaning) embeds only email that reaches the Mail agent, not newsletters, tool notices and other mail kept from the AI.

**Why:** Noted 2026-11-21. It embedded every email before the rules sorted anything, which wasted time and put mail the person keeps from the AI into what the AI can find.

**Today:** done in part on 2026-11-21. Setup sorts right after mail is connected, and the index takes no mail until sorting is done or skipped. After that it leaves out folders the AI doesn't read (`KEPT_MAIL` in `modules/semantic/module.py`).

**Left to check:** mail the header rules keep from the AI that isn't in such a folder, and Homes set up before sorting existed, which still have everything indexed (they may need a one-time clean-up of the index).

**Done when:** nothing kept from the AI, by folder or by rule, is in the index, on a new Home and on an old one.

## To try

- **Posty sees what the app shows** (built 2026-11-24, `docs/AGENT_SYNC_PLAN.md`): on the real account with the real model, ask "What needs me today?" and "what things have been completed". Check that answers cite matters and tasks as numbered chips with real titles, that nothing done shows as overdue (the RCA case), and that the Agents page shows no detour alert for a day question. Ask first, since it spends the ChatGPT allowance. Remember to restart the backend and rebuild the frontend first: a running backend doesn't pick up code changes (on 2026-11-24 an old backend made it look as if the change hadn't worked).
