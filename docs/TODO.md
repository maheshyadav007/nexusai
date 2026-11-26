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

Last reviewed 2026-11-25 (order of work rewritten after that day's fixes were merged). Removed as done that day: the compact hand-over in the chat panel (built in `8904a74`) and "Posty sees what the app shows" (built 2026-11-24, see `docs/AGENT_SYNC_PLAN.md`; trying it on the real account is under "To try").

Added 2026-11-25 from a review list of nine points: reading in parts (already item 2), the Q&A card (already in 4d, widened), labels (8), the size bar beside folders (4d), the morning password (9, a bug: look at it first), the triage card (4d), the Routines number leaving out built-ins (1), Done and Dismiss on brief lines (4f) and which agent owns what, starting from reminders (10).

## Order of work

Set 2026-11-25. Item numbers below stay as they are; this is the order to take them in. Mail is the product, and the agents must work on a weak model, so what breaks mail or wastes the model comes first.

**Done 2026-11-25** (merged in `16ec004`): mail signs in again by itself after a refusal (9, still to confirm on the company machine for a week), Notifications "Clear all", no `.ics` invites in Documents, no size bar beside folders.

**Small, still open:** nothing internal on screen (3): one naming helper for approval text and trace chips, plus a test that no raw key reaches the screen. Wording only.

**The big items, in order** (agreed 2026-11-25):

| # | Item | What it is |
|---|---|---|
| 0 | **One format: everything is a plugin (15)** | Agents, skills, connectors and routines as files in Anthropic's plugin format and names; the built-in ones ship as plugins. `docs/PLUGIN_FORMAT_PLAN.md`. Its step 1 (the loader, same behaviour) comes first, so 10, 7, 11 and 1 are each built once, on it |
| 1 | **Who does what (10)** | One owner per job. Posty does the small jobs directly (mail actions, tasks, reminders, folders, drafts; the Organizer folds into it); specialists keep jobs that need their own instructions (Mail agent, Brief writer, a new Routines agent, First meeting). `docs/AGENT_OWNERS_PLAN.md`. First, since 2 and 3 build on it |
| 2 | **Personalization (7)** | One tool to save what the person wants; their instructions outrank defaults. `docs/PREFERENCES_PLAN.md` |
| 3 | **Routines (1), with the Routines agent and repeating reminders (13)** | A routine is a condition and an action: on a time, on an email, on a check. The brief writer is the only default routine. Fixes the drink-water reminder and updates the prompts in the same iteration |
| 4 | **Tool-call optimization (2)** | One paging rule for every reading tool, and the "same call, same answer" guard. Small and helps every agent, so it may move first |
| 5 | **Zip through matters (4d) with brief Done and Dismiss (4f)** | List and matter scroll on their own, ↑↓ through matters, a pinned decision bar, one way to close a matter everywhere. Mockup first |
| 6 | **Plugins (11)** | Headers on MCP servers first, then skills and their tools as one install. `docs/PLUGINS_PLAN.md` |
| 7 | **Labels (8)** | The Mail agent tags mail by the person's rules, across folders |
| 8 | **Form filling from mail** | `docs/FORM_FILLING_PLAN.md`; may become an action a routine runs |
| 9 | **The NexusAI guide (14)** | Docs the agents search, like Claude Code's docs: foundations, concepts, how the app is built. Shipped as the `nexusai-guide` skill |

**Alongside, one mockup round for the screens:**
- Update progress in the status bar (4e), with time left. Raised again 2026-11-25, so first.
- The triage card (4d) and the Q&A card (4d), since both are chat cards.
- Grouped by state (4b).
- The shared waiting state (4a).

**Later:**
- Meeting prep from mail (12), once Routines (1) is built.
- Reaching Posty outside the app: Telegram, WhatsApp, or Teams at work (`docs/AGENT_HARNESS_PLAN.md`).
- NexusAI as an MCP server for company coding assistants, after a security review. See `docs/reference/LANDSCAPE_2026-11-25.md`.
- Name and identity (`docs/IDENTITY_PLAN.md`).
- Rollout on company machines (`docs/WINDOWS_RELEASE_PLAN.md`).
- Double-tap to open Posty (4c), vectorize only mail the AI reads (6, checks left), learn from Littlebird (5, hands-on).
- "To try" at the end: on the real account, when the model allowance allows.

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
- **Owned by a new Routines agent** (proposed 2026-11-25, see item 10): it sets up, changes and removes every kind of routine, so routines and reminders never get mixed up. Repeating reminders (13) are fixed in the same iteration.
- **A routine is a condition and an action** (agreed 2026-11-25). The person says it in plain words, and Posty turns it into a routine they keep or not. The two shapes to build first:
  - **On an email:** "when I get an email like this, do this" (for example: a request for the weekly status → draft it from the matter; an invoice → file it and add a task).
  - **On a check:** "monitor this endpoint for me, and send an email to these people when X" (X: it's down, it's slow, a value crosses a line). The check runs without a model; only the action may use one.
- **Starters:** a time (as now); an event, such as an email matching a rule or a plain-words description, a task coming due, or a check failing; or by hand.
- **Steps:** an agent prompt; a check that needs no model (from the monitors plan); fill a form or sheet (from the form plan). Later: call a connector's tool.
- **Tells:** Today, a notification, an email to a list; later Telegram and WhatsApp (see the Posty harness work).
- **History per routine:** each run's result, failures in a row, and when it last alerted, so a broken check doesn't email every minute.
- **Default routines:** only the brief writer for now. It becomes an ordinary routine, on by default, instead of a built-in kind with special code. Everything else ("Deadlines this week", the monitor examples) is a template the person can start from, never on by default.
- **Offered, not imposed:** like Sharpy, Posty can notice a repeated ask and offer a routine. Nothing runs until the person keeps it.
- **From the landscape review (2026-11-25, `docs/reference/LANDSCAPE_2026-11-25.md`):** email as a starter is what Littlebird added in October and what Linear's Loops are built on, so make it a first starter, not a later one. Each run keeps a history with **Resume** and **Run again** for a failed run (Linear). A **cost limit** per routine and overall, since runs spend the model allowance (Linear). **Save as routine** from a chat that worked, so a repeated prompt becomes one named routine (Linear, Scape, Littlebird). A template idea, not on by default: **Who owes me what** (a weekly look at conversations waiting on others, with nudge drafts; Fyxer, Littlebird). Meeting prep is later (item 12).

**Built-in routines don't count in the Routines number.** Noted 2026-11-25. The Routines button in the sidebar shows a number, and it counts the built-in routines too: `usePlannerCounts` in `frontend/ui/client/work.ts` counts every agent with a next run (`agents.filter((agent) => agent.next_run)`), so the Mail agent's hourly run and the morning brief are always in it. The person didn't make them and has nothing to do about them, so the number is never zero and means nothing. Count only routines the person made (their own schedules and triggers). Better still, make the number say something needs them, as the other sidebar numbers do (waiting chats, suggestions): a routine that failed, or a result not yet seen. Show nothing when all is well. Built-ins stay listed on the Routines page as now (`BuiltIn` in `SchedulesScreen.tsx`).

**Open questions:** how a mail starter is described (a fixed rule, a plain-words description judged by the mail agent, or both); whether a mail-started job runs inside the triage run or as its own run (its own run is safer and easier to see); how the brief's special parts (its sections, citations and Today card) fit a general routine without losing anything. For the Routines number: should it count the person's routines at all, or only ones that need a look (failed, or a result not yet seen)? Leaning: only ones that need a look.

**Done when:** the brief writer is the only default routine and runs with no special-case code; "when an email like this arrives, do this" runs on a test mailbox when a matching email arrives; "monitor this endpoint and email these people when it's down" checks without a model and emails once per failure; one page lists every routine with its last result.

## 2. How agents read: paging and limits

**What:** Every tool that reads something long can return it in parts, and says exactly how to get the next part.

**Why:** Noted 2026-11-25, and raised again in that day's review list. In a real run the agent could only get part of a file, so it called the same tool nine times with the same arguments, getting the same first part each time. That wastes tokens, and with a weak model it never recovers.

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

- **Notifications: Clear all.** Noted 2026-11-24. The notification centre (`frontend/ui/shell/NotificationCenter.tsx`) only clears one notification at a time; the backend has `notifications.list` and `notifications.markRead`. Add a "Clear all" that clears every notification in one step, with undo. Done when one click empties the list and undo brings it back. **Built 2026-11-25** (`notifications.clear` and `notifications.restore`; cleared ones are kept but never listed; clears the chosen type when filtered).
- **Documents: calendar invites listed as documents.** Noted 2026-11-25. The Documents page shows every `.ics` invite that came with an email, because attachments of kind `calendar` count as documents (`EMAIL_KINDS = ("attachment", "calendar", "risky")` in `modules/documents/module.py`). Invites aren't documents the person keeps; they clutter the list. Leave `calendar` out of the Documents list, or show an invite under the meeting or email it came with. The agent's tools may still read them. Done when Documents shows no `.ics` files and the agent can still read an invite from its email. **Built 2026-11-25** (`LISTED_KINDS` in `modules/documents/module.py`; reading by key still finds invites).
- **Matters tab: zip through and decide.** Noted 2026-11-25, after the Sharpy cards. On a big screen we don't need cards; make the existing Matters tab (`frontend/ui/features/today/matters/MattersTab.tsx`) fast to go through. The list and the matter each scroll on their own; ↑↓ moves through matters and opens each one at once; a decision bar pinned at the top of the matter (it never scrolls away) shows one line of what Posty suggests, with **Keep (K)**, which keeps its suggestions as the person's work, and **Not for me (X)**, which declines them and marks the matter done. After either, the next matter opens, with Undo in a toast. A matter with no suggestions shows only Done and Next. It uses existing actions (accept and decline for suggestions, `matters.done`, undo). Sketched in chat on 2026-11-25; needs a visual mockup and approval before building. Open: should "Not for me" also offer "stop reading this sender"? The suggestion was no at first.
- **Q&A card.** Noted 2026-11-25, and raised again in that day's review list. When Posty asks something with `ask_user`, the chat shows a question card (`QuestionCard`, and `AnsweredQuestion` once answered, in `frontend/ui/features/assistant/Cards.tsx`; placed by `ChatView.tsx`). Improve it **while it's waiting**: the question first, clear options as buttons, a free answer box, one line on why it's asked, and it stays in view until answered. And **after it's answered**: fold to one line, the question and the answer chosen, which opens back up on a click. Needs a mockup.
- **Size bar beside folders: remove it.** Noted 2026-11-25. Each top-level folder in the sidebar has a small bar in front of its name showing its size against the biggest folder (`size: count / biggest` in `ui/shell/HomeNav.tsx`, drawn with `Progress` in `ui/shell/FolderLink.tsx`, added in `50dd905`). It adds clutter and tells the person nothing they need; the folder tree and its unread counts already say where things are. Remove the bar and the `size` prop, and check the row still lines up with and without unread counts. Done when no folder row shows a bar. **Built 2026-11-25.**
- **Triage card: show everything decided.** Noted 2026-11-25. When the Mail agent judges an email, the chat shows `TriageCard` (`frontend/ui/features/assistant/Cards.tsx`) with only the folder, an "Important" tag, the summary and the reason. `record_triage` (`_RecordTriage` in `modules/agent/tools.py`) records far more: status (waiting on you or others, fyi, resolved), next action, follow-up date, smart folders, notify, confidence and why it wants a review, deadlines, the matter, tasks, reminders, what's finished, a draft, what it learned, and a question for the person. Show all of it, laid out so the card still reads at a glance: a first line with the folder, status and importance; the summary and the reason; then labelled rows only for what's set (follow up on, deadlines, matter, suggested tasks and reminders, draft), and confidence when it's low. Use the same names the rest of the app uses (the matter states, "Waiting on you"). Needs a mockup. Also from the landscape review (Linear's triage): what the agent suggests stays visibly apart from what the person set, each suggestion shows its reason, and later the person can switch on "do this by itself" for one kind of suggestion at a time (for example filing newsletters), once they trust it; that switch is a preference (item 7). Done when every field `record_triage` can set appears on the card when it's set.

### 4e. Installing an update shows in the status bar

**What:** While a new version downloads, installs and starts for the first time, the app says so: a progress bar where the progress is known, and at least a line in the status bar at the top ("Installing version 0.9.3…") where it isn't.

**Why:** Noted 2026-11-25. Installing a new version is silent. Nothing appears in the status bar at the top, so the person can't tell whether the app is updating, stuck or broken. The same happens when a new version first starts: it may back up the whole Home (about 2 GB on the real account) before the database upgrade, and the app shows nothing meanwhile.

**Today:**
- The desktop app downloads and installs with `electron-updater` in `desktop/main.cjs`. `updateState` holds `state` (checking, available, downloading, error…) and `percent`. Progress shows only in the taskbar or Dock icon (`window.setProgressBar`) and in the app menu's update item ("Downloading update: 42%"). After the download, `installBeside` installs next to the running version, then `markReady`.
- The page reads that state through `window.nexusDesktop` (`frontend/ui/client/desktop.ts`, query `nexus:status`). Only Settings › About & Updates shows it (`frontend/ui/features/settings/DesktopUpdates.tsx`).
- The status bar at the top is `frontend/ui/shell/ActivityIsland.tsx`. It shows running agent work, or "Nothing running" (`activity.idle`), and knows nothing about updates.
- On the first start of a new version, the backend backs up the Home when database migrations are pending (`backups.create(home, "upgrade", …)` in `backend/src/nexusai/api/app.py`), then runs them. Requests can fail meanwhile. While testing on 2026-11-25, the health check answered "Internal Server Error" for a few seconds.
- The desktop's start-up window (`desktop/loading.html`) shows a line per stage (`startupStage(…)`), but nothing for the backup or the upgrade.

**Raised again 2026-11-25:** updating is "very silent"; the person can't see what's happening. Show progress, and a time left wherever it can be worked out.

**Approach:** one "app update" state that the status bar shows like any other running work: downloading with a percentage, installing, ready to restart (with a Restart button), and on the next start "Backing up and upgrading your data…". Use a progress bar where a percentage is known (the download; the backup if it can report one). The start-up window gets the same lines for the backup and the upgrade. In the browser version, where there's no installer, only the start-up part applies.
- **Time left:** `electron-updater`'s `download-progress` event already gives `transferred`, `total` and `bytesPerSecond`, so the download shows "42% · about 2 min left" (smoothed, so it doesn't jump). The backup can do the same if it reports bytes copied against the Home's size. Steps with no measure (installing, the database upgrade) show a moving bar and how long they've taken so far, never a frozen screen.
- **Every step has a line:** checking, downloading, installing beside the running version, ready to restart, backing up, upgrading data, starting. If a step fails, the line says so with Try again, instead of going quiet.

**Open questions:** can the backup report progress (bytes copied out of the total), or only a line? Should "ready to restart" ask once, or wait in the status bar until the person chooses?

**Done when:** from clicking Update to the new version's first screen, the person can always see what the app is doing, with a percentage and time left for the download and, if possible, the backup. Checked with a real update from one version to the next, on a Home large enough that the backup takes noticeable time. Approved from a mockup first.

### 4f. Brief lines: Done and Dismiss on each

**What:** Each line in the brief on Today gets **Done** and **Dismiss**, which change its matter directly. The line then says what happened, instead of "updated 10:42".

**Why:** Noted 2026-11-25. The brief is now a list of changes, one line per matter, so it's the natural place to act on each one. Today the person goes elsewhere to act, and when they do (for example, dismissing "waiting on you" on a conversation), the brief only marks the line "updated 10:42", which doesn't say what changed or that it was their own doing.

**Today:**
- Brief lines are drawn in `BriefSections` (`frontend/ui/features/today/TodayScreen.tsx`): the line's text, plus a mark from `today.brief.added` or `today.brief.updated` ("updated {when}"). No actions.
- `briefs.follow` (`modules/agent/briefs.py`) keeps the brief in step with each matter without a model. A matter that's done leaves the brief (and shows under Done since yesterday). Any other change rewrites the line and marks it `updated`, whatever the change was and whoever made it.
- Matters can be closed and reopened (`matters.done`, `matters.reopen` in `modules/agent/module.py`). There's no "dismiss" for a matter: dismissing "waiting on you" changes the conversation's status (`thread.setStatus`), and the matter's state follows from its conversations (`matters.row`).

**Approach:**
- On each line, **Done** (`matters.done`) and **Dismiss**, with Undo in a toast (`matters.reopen` or the status put back).
- Agree what Dismiss means first: "nothing for me to do here" (the matter's conversations to fyi, so it leaves Priority and the brief's waiting lines) or "not interested in this matter" (done, without counting it as finished work).
- The mark says what happened and who did it: "Done by you 10:42", "Dismissed 10:42", "They replied 10:42", "New mail 10:42". `briefs.follow` is told what changed by whatever called it (the person's action, a new email, the agent), rather than always writing `updated`.
- A line the person closed fades out after Undo has passed, rather than jumping away.
- Shares its actions with the Matters tab's decision bar (4d), so there's one way to close a matter everywhere.

- Later, from the landscape review (Littlebird): reply to the brief in Posty ("push that to Friday", "done with Kite"), using the same actions.

**Open questions:** what Dismiss means (above); whether lines also need "Snooze until tomorrow".

**Done when:** Done and Dismiss on a brief line change the matter, Undo puts it back, and every mark on a line says what changed. Approved from a mockup first.

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

## 7. Preferences: one tool, the fewest places

**What:** Everything the person wants from Posty, the Mail agent and the Brief agent is saved by one tool (`save_preference`), called wherever they say it (chat, the brief, the first meeting, Settings), into one place for instructions (the `preferences` table). Each agent reads its instructions as one section and is told they come before its own prompt and every default.

**Why:** Noted 2026-11-25. Today nine places shape what the agents do, written by four tools (`save_personal_prompt`, `propose_preference`, `remember`, the Prompts tab), and only the Brief agent is told the person's wishes outrank its defaults. The same wish can land in memory, a brief comment, a preference or a prompt file depending on where it was said.

**Today, approach, open questions and steps:** written out in full in `docs/PREFERENCES_PLAN.md`.

**Done when:** as in that plan, section 9: one row per instruction wherever it was said, one "Your instructions" section per agent ranked above its defaults, and no other place storing instructions. Checked on the real Gmail account.

## 8. Labels from what the person wants

**What:** The person can say how they want mail labelled ("label anything about the Kite launch *Kite*", "anything with an invoice *Finance*"), and the Mail agent labels each email that way as it judges it. A label is a tag: an email can have several, and labelling doesn't move it out of its folder.

**Why:** Noted 2026-11-25. Folders decide where mail lives and whether the AI reads it. People also want to mark mail across folders by project, client or kind, the way Gmail labels work, without moving it.

**Today:**
- Each conversation has one folder (`threads.category`) and can also show in extra ones (`threads.extra_categories`). The Mail agent picks those with `category` and `smart_folders` in `record_triage` (`modules/agent/tools.py`; "at most one existing smart folder").
- Gmail's own labels come from the server and are shown read-only under More › Labels (decision D2 in `docs/FOLDERS_PLAN.md`). NexusAI doesn't set Gmail labels; `imap.py` only removes them when moving.

**Approach:**
- Decide first whether labels are a new thing or what smart folders become. Smart folders already let one conversation show in several places; a label could be a smart folder that's shown as a tag on the row as well as a place in the sidebar. That would avoid a second, overlapping feature.
- Labels belong to the Mail agent, not to preferences (item 7 is personalization). The person's label rules ("label X when …") are kept with the labels themselves, said in chat or on the label, and the Mail agent applies them while judging mail.
- Labels show as small tags on mail rows and in the conversation, and can be filtered by.
- Ask whether labels should go back to Gmail (as real Gmail labels) or stay in NexusAI.

**Open questions:** labels as their own thing or as smart folders shown as tags (leaning: the latter); writing to Gmail labels or not; whether the agent may suggest new labels or only use the person's.

**Done when:** a label described in chat is applied by the next triage run on a test mailbox, shows as a tag, and can be filtered by. Approved from a mockup first.

## 9. Mail stays connected overnight (bug)

**What:** Mail must reconnect by itself after a night, without asking for the password again, unless the password is really wrong.

**Why:** Noted 2026-11-25. A person on the company (POP3) setup has to type the password every morning or mail doesn't connect.

**Today:**
- The password is saved once, in a local secrets file that survives restarts (`LocalStore` in `kernel/secrets.py`, falling back to what's in the OS keychain), and read by `accounts.get_password`. Nothing clears it overnight, so it's probably not being forgotten.
- **The likely cause:** when the server refuses a sign-in, mail sync stops for good. `_run` in `modules/mail/sync.py` catches `SignInFailed`, sets the state to "failed" ("The mail server refused the username or password.") and returns, with no retry. Only saving the password again starts sync again, which is what the person ends up doing each morning.
- For POP3, almost any `-ERR` reply to the password counts as a wrong password (the login in `Pop3Session`, `modules/mail/pop3.py`). Only replies containing `IN-USE`, `SYS/TEMP` or `LOCK` (`BUSY_REPLIES`) are treated as "busy, try later". Company servers often refuse for a while for other reasons: a nightly restart or maintenance, the directory server being unreachable after the laptop wakes on a different network, or another mail program holding the mailbox, with wording our list doesn't catch. IMAP has the same shape (`SignInFailed` from `imap.py`).

**Built 2026-11-25 (branch `mail-sign-in-retry`):** a password that has signed in before is no longer given up on at the first refusal. Sync tries again after 5, 10 and 20 minutes, saying "The mail server refused the sign-in. Trying again…", and asks for the password only after 4 refusals in a row (about 35 minutes), or at once for a password just typed. Waits between these tries aren't cut short by local work, so they can't spend tries faster. The server's exact reply is logged (`mail_sign_in_refused`) and shown in Status when it does ask. Tests: `test_a_saved_password_refused_one_morning_is_tried_again_without_asking`, `test_a_password_refused_every_time_is_asked_for_after_a_few_tries`. **Still open:** confirm on the company machine for a week; retry at once on wake or network change; the open questions below.

**First step (still useful):** confirm the cause. On the company machine, read the backend log for the morning's `mail_sync` state change and the server's exact `-ERR` text, and check when it happens (on wake, at a fixed time, after the laptop was off the company network).

**Approach (once confirmed):**
- A refused sign-in is not final at once. Keep the password, back off and retry (as `ConnectionFailed` does now), and say "The server refused sign-in; trying again" instead of asking for the password.
- Ask for the password only when the refusal is clearly about the password (an `[AUTH]` response code, or the same refusal several times in a row over a set time, such as 3 tries over 30 minutes), or as soon as the person changes it.
- Retry at once when the computer wakes or the network changes, rather than waiting for the next timer.
- Add the server's exact reply to the status the person sees and to the log, so the next problem like this can be read from Status.
- Tests with the fake POP3 and IMAP servers: a temporary refusal, then success, reconnects with no password asked; a real wrong password still asks.

**Open questions:** how many refusals over how long before asking (three over 30 minutes is a starting point); whether a locked account (too many tries) needs its own message so retries don't lock it further.

**Done when:** on the company machine, mail reconnects by itself every morning for a week with no password asked, and a wrong password still asks at once.

## 10. Who does what: one owner for each job

**Steps 1–3 built 2026-11-26** on `plugins-loader`: `jobs.py` names the owned jobs (triage and suggestions for the Mail agent, the brief for the Brief writer) and every refusal names the owner; the Organizer is folded into Posty, which keeps tasks and reminders in its own run; its chats and team tasks moved to Posty by migration. Not yet: the Mail agent losing drafting and suggestions in chat (open question 2–3), and agents the person makes losing specialists' tools (with Routines).

**Plan:** `docs/AGENT_OWNERS_PLAN.md` (2026-11-25), written with personalization (7) in mind. **Reorganised the same day:** small jobs that need few instructions go to Posty directly; only jobs needing their own instructions, running without the person, or reading untrusted mail at scale get a specialist. The Organizer folds into Posty. The table and questions below are the first draft; the plan supersedes them.

**What:** Write down which agent owns each kind of work (tasks and reminders, judging mail, drafts, the brief, matters, folders and rules, routines, preferences), and make the tools match: the owner makes and changes it, others read it, suggest it, or hand the work to the owner. Then every agent's prompt says the same split.

**Why:** Noted 2026-11-25. Asked first as "reminders with Posty only?", then widened: setting and managing reminders is the Organizer's job today, and responsibilities need planning properly across agents, not reminder by reminder. Today the split has grown one tool at a time and has gaps and overlaps (below), so it's unclear who made something, a weak model can pick the wrong path, and two agents can make the same thing.

**Today** (tool sets in `modules/agent/tools.py`, prompts in `modules/agent/prompts/`):

| Agent | Card / prompt | What it can do now |
|---|---|---|
| **Posty** (lead, `session`) | `session.md` | Every tool, except those withheld as the Organizer's (`withheld_for`: `ORGANIZER_ONLY`) and those only the Mail or Brief agent may use. Hands work out with `team_assign`. Shown first: `LEAD_SHOWN`. |
| **Mail agent** (`mail`) | `mail.md` | Judging an email: `TRIAGE_TOOLS`, ending with `record_triage`, which also suggests tasks, reminders, deadlines, a draft and a matter. Otherwise (chat, team tasks): `MAIL_AGENT_TOOLS`: reads, drafts, `propose_task`, `propose_reminder`, `propose_preference`, `notify_person`; `update_mail` only on a team task. |
| **Brief agent** (`daily-prep`) | `daily-prep.md` | `BRIEF_TOOLS`: reads and searches, writes the brief (`update_brief`), lists tasks and reminders, and can `draft_reply`. |
| **Organizer** (`organizer`) | `organizer.md` | `ORGANIZER_TOOLS`: creates, changes and deletes tasks and reminders, reads mail to link and date them. |
| **First meeting** (`interview`) | `interview.md` | `INTERVIEW_TOOLS`: asks, saves personal prompts, applies what was learned from mail. |
| **Agents the person makes** (cards, `modules/agent/cards.py`) | their card | **Every tool** (`allowed_for` returns `None` for any other agent), including making and deleting tasks and reminders. |

Gaps and overlaps found:
- **Suggesting tasks and reminders:** `propose_task` and `propose_reminder` are in `ORGANIZER_ONLY` (withheld from Posty as the Organizer's), but the Organizer doesn't have them. Only the Mail agent can use them, and it can also suggest the same through `record_triage`'s `tasks` and `reminders`. Two paths in one agent, none in the owner.
- **Agents the person makes** can do everything Posty can't, including the Organizer's work, since nothing is withheld from them.
- **Drafts:** Posty, the Mail agent and the Brief agent can all draft replies.
- **Preferences:** `propose_preference` (Posty, Mail agent), `save_personal_prompt` (first meeting), `remember` (everyone). Being brought into one tool by item 7.
- **Matters:** joined by code (`matters.link`) and by the Mail agent (`matter` in `record_triage`); closed by the person. No agent owns closing or merging.
- **Folders, rules, routines:** only Posty (`create_categories`, rules, `create_schedule`), through "every tool"; no prompt says it owns them.

**Approach:**
- **One rule:** each kind of thing has one owner that makes, changes and removes it. Others may read it; agents that see it in mail may **suggest** it (saved as a suggestion for the person to keep); anything else goes to the owner with `team_assign`.
- **A proposed split** to agree on:

| Job | Owner | Others |
|---|---|---|
| Talking with the person, routing work | Posty | — |
| Judging mail: folder, status, importance, matter, follow-up | Mail agent | Posty changes it only when the person asks, through `update_mail` |
| Tasks and reminders: make, change, complete, remove | Organizer | Mail agent suggests (only through `record_triage`); Posty and others hand over |
| Drafts and replies | Mail agent | Posty asks it; the Brief agent links to mail instead of drafting |
| The brief | Brief agent | — |
| Matters: close, merge, split | the person, through Posty | Mail agent joins mail to them |
| Folders and rules | Posty | — |
| Routines: set up, change, pause, remove (on a time, on an email, on a check) | **Routines agent** (new, proposed 2026-11-25) | Posty and others hand over; the Brief agent runs the brief routine but doesn't set routines up |
| Preferences | one tool (item 7), whoever hears it | — |
| Agents the person makes | only what their card lists | never the owners' tools unless the card says so |

- **Make the tools match:** one owner list in `tools.py` (a table from job to owning agent) that `allowed_for` and `withheld_for` both read, so a tool can't be "owned" by an agent that doesn't have it. Remove the Mail agent's separate `propose_task` and `propose_reminder` if `record_triage` covers it. Give person-made agents a default set, not every tool.
- **Make the prompts match:** each prompt gets a short "Yours / Not yours" section from the same table, and the team roster (`team_roster`) shows each agent's jobs so handing over goes to the right one.
- **Every item says who made it:** tasks, reminders, drafts and folders show their maker ("Suggested by the Mail agent from Priya's email").
- A test that walks the table: each job's tools are allowed for its owner, withheld from the rest, and named in the owner's prompt.

**Open questions:**
- **A separate Routines agent** (the person's proposal, 2026-11-25): one agent that sets up every kind of routine, so the difference is clear: "remind me" goes to Posty, "do this when…" or "every hour, check…" goes to the Routines agent. Its card, prompt and tools (`create_schedule` and the routine tools from item 1) are made in the same iteration as Routines.
- Should reminders stay separate from tasks, or become a task with a "remind me" time, so the Organizer keeps one list?
- Should the Mail agent still suggest tasks and reminders while judging mail, or only mark deadlines and leave making them to the Organizer?
- Drafting: only the Mail agent, or Posty too when the person is talking to it?
- What a person-made agent gets by default.

**Done when:** the table is agreed, `tools.py` reads it for every agent, each prompt says what's its own, the walking test passes, and on the real account asking Posty for a reminder, a task from an email, and a draft each goes to its owner.

## 11. Plugins: skills and their tools as one install

Added 2026-11-25. Plan: `docs/PLUGINS_PLAN.md`.

**Why:** skills and connectors are added in two places today, and nothing links a skill to the MCP server it needs. Claude Code, Codex, VS Code/Copilot (Agent Plugins 1.0) and Gemini CLI all bundle them now as a plugin: a folder with `plugin.json`, `skills/` and an MCP file.

**Plan in short:** read the portable layout and Claude's and Codex's, so their plugins install unchanged. Use skills and remote MCP servers; show the rest as "not used here". One review, one hash, one switch, one remove. Secrets asked on install and kept in `secret_store`. A plugin's tools only appear once its skill is loaded, to keep a weak model's tool list short.

**Headers on MCP servers (first step, on its own):** some servers need an `X-API-Key`, a tenant id or a gateway header, but a connector today takes only a bearer token (`connectors/client.py`). Add a list of headers to each connector: names in the database, every value a secret in `secret_store`, never shown again or given to the agent; the MCP client's own headers can't be overridden; a change lists the tools again. Plugins reuse it, filling `${user_config.KEY}` on install. The Connectors form gets "Add header" rows (mockup first). Done when a server that needs an `X-API-Key` header can be added, tested and used, and its value is in neither the database nor any response. See `docs/PLUGINS_PLAN.md`.

**First plugin to prove:** a company tool (an issue tracker or wiki over MCP), since mail at work keeps pointing to tickets and pages (landscape review).

**Steps:** headers on MCP servers → read a plugin → install and remove through Posty (mockup for the card) → settings and secrets → tools come with the skill → Agents page list (mockup) → later OAuth, catalogs, local servers.

**Done when:** one Claude Code plugin from a GitHub URL gives Posty its skill and tools after one review, turning it off removes both, a change at the source turns it off until approved, and removing it leaves nothing behind.

## 12. Meeting prep from mail

Added 2026-11-25 from the landscape review (`docs/reference/LANDSCAPE_2026-11-25.md`). **Later:** after Routines (1). Plan only.

**What:** before a meeting, a short prep: who's coming and how the person knows them, the matter it's about, what's still open, what each side promised, and the last few emails. After it, a nudge to note decisions and follow-ups. No recording and no screen reading: only what's already in NexusAI.

**Why:** days at a company are meetings, and Littlebird and Fyxer both lead with meeting prep. NexusAI already holds what prep needs: invites arrive as `.ics` attachments, and matters know the conversations, people and open items.

**Today:**
- `.ics` invites come in as attachments (and show in Documents, which 4d removes). Nothing reads them into a meeting with a time and attendees.
- Matters link conversations, tasks and people (`matters.link`); the brief already writes per-matter lines without a model (`briefs.follow`).

**Approach:**
- Read each `.ics` invite into a meeting: time, title, attendees, and the conversation it came in.
- Link the meeting to its matter by its conversation, then by attendees and title.
- A Routines template (item 1), not on by default: "Prep before each meeting", run a set time before it starts; the result is a card in Today and a line in the brief.
- Who owns it is part of item 10 (likely the agent that writes the brief).

**Open questions:** how long before a meeting; whether updates and cancellations to an invite move or drop the prep; whether to read a calendar later (Google Calendar, the company calendar) or stay with invites in mail.

**Done when:** an invite in a test mailbox gets a prep card before its time, linked to the right matter, with open items and the last emails. Approved from a mockup first.

## 13. Repeating reminders, and reminders vs schedules (bug)

**Built 2026-11-26** on `plugins-loader`: reminders repeat every N minutes (`interval`), on chosen days, between two times, until a date; the tool takes `hourly` or `every 2 hours` too; a missed firing isn't repeated; a schedule whose instructions only remind is turned to `create_reminders`; Posty's prompt says "remind me" is always a reminder; the Reminders page shows the rule in words and keeps it when a reminder is edited. Tests: `tests/test_reminder_rules.py`. To try on the real model: the drink-water request, said to Posty in those words (ask first).

**When:** decided 2026-11-25: built together with Routines (1) and who does what (10), in one iteration, since the fix is the reminder/routine split plus the prompts. Not a separate quick fix.

**What:** "Set an hourly reminder to drink water from 10am to 8pm, Monday to Friday" can't be set today, and the agent mixes up reminders and schedules while trying. A reminder must be able to repeat like that, and the agent must always pick a reminder for "remind me".

**Why:** Noted 2026-11-25 on the person's own request.

**Today:**
- A reminder repeats only `none`, `day`, `week`, `month` or `year` (`Repeat` in `contracts/planner.py`, `REPEATS` in `modules/planner/module.py`). No hourly, no chosen weekdays, no "between 10:00 and 20:00".
- A schedule can run `hour` or `weekdays` (`every` in `modules/agent/scheduler.py`), but not both together, and not within a window. And a schedule runs an agent with a prompt; it isn't a reminder.
- So neither tool can say what was asked. The model tries one, gets refused, tries the other, and ends up with a schedule that wakes an agent every hour to "remind" (spending the model allowance) or with nothing.

**Approach:**
- **One rule:** a reminder only tells the person something at a time, with no model, and is Posty's (the Organizer folds into Posty, `docs/AGENT_OWNERS_PLAN.md`). A routine (item 1) makes an agent do work, and belongs to the new Routines agent. "Remind me" is always a reminder. Written into the owner table (item 10), the tool descriptions and the prompts.
- **Reminders repeat richly:** every N minutes or hours, on chosen weekdays, between a start and end time, with an optional end date. "Hourly, 10:00–20:00, Mon–Fri" is one reminder that fires 11 times a day. Daily, weekly, monthly and yearly stay as they are.
- **Firing:** each time it goes off is a notification; one that wasn't seen isn't repeated, and the next time is worked out from the rule, as `next_due` does now.
- **Guard:** a schedule whose prompt is only "remind me to …" is refused with a message pointing to the reminder tool, so a weak model can't take the wrong path.
- **On screen:** the reminder shows its rule in words ("Every hour, 10:00–20:00, Mon–Fri"), and can be paused or stopped as one. Any form change needs a mockup.

**Done when:** the drink-water request, said to Posty in those words, makes one reminder (no schedule) that fires hourly 10:00–20:00 on weekdays and not at weekends, with no model run per firing; and a "remind me" asked as a schedule is turned to a reminder. Fake-model tests; a real-model check only after asking.

## 14. The NexusAI guide: docs the agents can search

Added 2026-11-26.

**What:** a set of short pages, like Claude Code's docs, that say what NexusAI is and how it works: the foundations (local-first, nothing leaves without a yes, undo), the concepts (matters, folders and Priority, the brief, agents and jobs, skills, connectors, plugins, routines, instructions and memory), how to do things ("make a routine", "add a connector", "why was this marked important"), and how the app is built (modules, events, the plugin format). Posty and the other agents search it to answer "how do I…", "why did you…" and "what can you do", instead of guessing.

**Why:** today an agent explaining the app answers from its prompt, which is either too long or out of date. Claude Code answers questions about itself the same way: a docs site and a guide agent that reads it.

**Approach:**
- Pages in `docs/guide/*.md`, one topic each, with frontmatter `title` and `description` (the same two-step shape as skills). Written for end users first; a "How it's built" section for the agents and for people extending it with plugins.
- Shipped as the skill `nexusai-guide` in the built-in `nexusai` plugin (`docs/PLUGIN_FORMAT_PLAN.md`): its `SKILL.md` lists the pages by title and description, and pages come with `read_skill_file`. Searched with the same local search the documents use, so it costs no model call to find the right page.
- Kept true by a test: every agent, skill, job, routine trigger and setting named in the code has a page or a line on one, and every page's names exist in the code.
- The plans in `docs/*_PLAN.md` stay for us; the guide says only what's built.

**Done when:** asked "how do I make a routine?", "what does the Mail agent do?" or "why is this in Priority?", Posty loads the guide, cites the page, and answers right, on the fake model in tests; and on the real model after asking.

## 15. One format: everything is a plugin

Added 2026-11-26. Plan: `docs/PLUGIN_FORMAT_PLAN.md`.

**What:** agents, skills, connectors and routines are files in Anthropic's Claude Code plugin format, with Anthropic's file and field names (`agents/<name>.md`, `skills/<name>/SKILL.md`, `.mcp.json`, `plugin.json`, `name`, `description`, `tools`, `skills`, `mcpServers`, …); what only NexusAI has sits under `nexusai`. The agents, skills and routines that ship with the app are plugins too (`nexusai`, `mail`, `brief`, `routines`, `meetings`). The person's own things are a plugin, `yours`, kept in the encrypted database. A company layer sits on top.

**Why:** the person, 2026-11-26: one file per agent in Markdown with frontmatter, skills the same, plugins that can be installed, all in the same form, the only difference being which ones ship with the app; use the names Anthropic uses; and build it once. Items 10, 7, 11 and 1 each touch these shapes, so the format comes first.

**Steps:** see the plan's §13. Step 1, the loader with no change in behaviour, before item 10.

## To try

- **Posty sees what the app shows** (built 2026-11-24, `docs/AGENT_SYNC_PLAN.md`): on the real account with the real model, ask "What needs me today?" and "what things have been completed". Check that answers cite matters and tasks as numbered chips with real titles, that nothing done shows as overdue (the RCA case), and that the Agents page shows no detour alert for a day question. Ask first, since it spends the ChatGPT allowance. Remember to restart the backend and rebuild the frontend first: a running backend doesn't pick up code changes (on 2026-11-24 an old backend made it look as if the change hadn't worked).
