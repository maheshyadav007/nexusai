# Posty sees what the app shows

Planned 2026-11-24. Not built yet. Each step below is meant to be built, tested and merged on its own, in order.

## Why

Asked "What needs me today?", Posty took 14 steps: it read the work board, listed open tasks and reminders, and searched mail four times. It never looked at a matter. It then said the first RCA for Carrier X was overdue, when that task had been ticked at 21:45.

The cause isn't one bad answer: **the app and Posty have two different pictures of the person's work.** Today is built from matters (their state, kept and suggested work, "looks done", done since yesterday, the live brief). Posty rebuilds its picture from mail and older lists. Every feature added to Today widens the gap, because Posty's tools don't change with it.

## What's wrong today

Found by reading the code on 2026-11-24.

1. **No way to see all matters.** `read_matter` (`modules/agent/tools.py`) opens one matter, but only by number. Nothing lists them. `read_plate`, the one tool with the whole picture, is limited to the brief agent (`BRIEF_AGENT_ONLY`).
2. **Finished work is hidden.** `list_tasks` leaves out done tasks by default; `list_reminders` leaves out ones that went off (`modules/agent/work_tools.py`). An email still reads as an open ask after the work is done.
3. **Mail results don't say where things stand.** `search_mail` and `read_thread` return emails with nothing about their matter's state or work.
4. **Two records of the same work.** `read_work_board` says "Check this first", but the work board (`work_board` table) overlaps matters and tasks. Posty's first step was the board, not matters.
5. **No prompt rule on where to start** for questions about the day or about how something is going (`prompts/session.md`, `prompts/system.md`).
6. **Posty is never told how NexusAI organizes work:** what a matter is, what it owns, links, states, kept vs suggested work, folders as the AI's gate.
7. **Citations cover only mail and documents.** `citations.MARKER` knows `mail` and `doc`; `sources.describe` the same. A matter, task, reminder or Home file can't be cited or opened from an answer.
8. **Addresses are mixed and sometimes raw.** Attachments appear as `read_document key m:12:2` (`tools.py`, `read_thread`), and the prompt's example is `[doc:m:45:2#p3]`, so internal keys leak into answers. The same object is written `task:88`, `88: title`, `[1]` (matters in triage context) or "related matter 7".

## Decisions already made

- **One view, two forms.** The code that builds Today's data also writes Posty's text version of it. Posty can't see something different from the app.
- **Posty decides where to start, from its prompt. No routing code, no rule matching on the question.**
- **The "Your day" summary is in front of Posty on every message** (about 300–500 words). The prompt can only point to what's there, so the two stand or fall together.
- **Posty learns the object model**, and objects are handled the object-oriented way: one address per object, opened with one tool that shows its links.
- **One address is also the citation**, for every kind of object.
- No real-model evals without asking first; fake-model tests are fine. The target is a low-capability model, so context carries the quality, not tool choice.

## The object model Posty is taught

This is what the prompt section says, in short. The lists of kinds, states and link types are filled in from code (step 2).

- **Email → conversation → matter.** A matter is one real thing going on, however many conversations it took.
- **Ownership is a tree.** A matter owns its conversations, tasks (and their reminders), deadlines and files. Each belongs to one matter.
- **Links for the rest:** related matters, merged ones, files attached from elsewhere. Linked things stay separate; when it's unclear whether two belong together, the person decides.
- **States:** waiting on you, waiting on others, worth knowing, done. Code works them out from the conversations and work; Posty doesn't set them.
- **Kept vs suggested.** Only what the person kept is theirs. A suggestion waits in For your decision. "Looks done" means a later email shows it finished; the person confirms.
- **Folders:** Read by AI vs Kept from the AI (the folder is the AI's gate), Priority on top, rules file mail before Posty sees it.
- **The brief and Today are views of matters**, not separate data.

## Addresses and citations

One form, used to read, cite and act:

| Kind | Address | Opens |
|---|---|---|
| Matter | `[matter:12]` | The matter page |
| Task | `[task:88]` | Its row on Tasks, or its matter |
| Reminder | `[reminder:5]` | Its row on Reminders |
| Email | `[mail:123]`, `[mail:123#m456]` | The quick preview, as now |
| Document or attachment | `[doc:KEY]`, `[doc:KEY#p3]` | The document preview, shown by name, never by key |
| Home file | `[file:path]` | Documents |

## Steps

### 1. The shared day view and "Your day"

- One function builds the day's data: matters waiting on you and on others (each with its open kept work, suggestions, "looks done", due date and latest email), matters with only suggestions, done since yesterday, decisions waiting, and the brief's lead line. Today's queries (`matters.brief`, `today.view`) and Posty both use it.
- A text form of it, addressed as in the table above, goes in front of Posty on every chat message.
- **Done when:** asked "What needs me today?", a fake model given only the summary can answer correctly, and a test shows the summary lists the same matters and counts as Today.

### 2. The object model in the prompt

- A short "How NexusAI organizes your work" section in the chat prompt, as above.
- The lists of object kinds, states and link types are filled in from the code's own definitions (`contracts`, `matters.py`, `links.py`).
- **Done when:** a test fails if the prompt's lists and the code's disagree.

### 3. One address per object, and `open()`

- `open(address)` returns the object, its owner, its state, and its links, each as an address to open next. It replaces `read_matter`, `list_tasks`, `list_reminders` and `read_work_board` for reading. A companion `find(words or state)` lists matching matters, so nothing needs a number known in advance.
- Every tool prints objects only by address. `search_mail` and `read_thread` add one line per conversation on where it stands, for example "[matter:12] done · [task:88] ticked 21:45".
- Lists of tasks and reminders include the last two days of finished ones, marked done, with when.
- **Done when:** no tool output has a bare id or key, and every address a tool prints can be opened.

### 4. Citations for every kind

- `citations.MARKER` and `sources.describe` cover every kind in the table. The quick preview and the citation list open each one.
- The prompt's citation rule covers all kinds, with examples that show no internal keys.
- The answer is checked before it's shown: a raw key (`m:12:2`, `task:88` without brackets) becomes a citation where it can, or is dropped. The "cites nothing" check counts matters and tasks too.
- Uses today's citation look; show a mockup only if the person asks for one.
- **Done when:** a raw key never reaches the screen, and each kind opens from an answer.

### 5. Where to start, and how to answer (prompt only)

- In the chat prompt: for the day or what needs them, answer from "Your day"; for how something is going, open that matter; search mail or documents only for what those don't cover, or to show the email behind a point.
- Answers about the day take the brief's shape: what matters most, new, still open, done. One line per matter, each cited.
- **Done when:** fake-model tests for these questions pass with no mail search.

### 6. One record of the work

- The work board's deadlines become dated tasks in their matters; other agents write work through the same matter actions the app's buttons use.
- `read_plate` and `read_work_board` are retired; the brief agent reads the shared day view.
- This is the largest step, because other agents write to the board. Plan its migration before building it.

### 7. Staying in sync

- Tests: prompt vs code (step 2), Posty's view vs Today (step 1), every address opens (steps 3–4), fake-model answers (step 5).
- A Cockpit trace check flags a run that searched mail before looking at matters, so a slip in following the prompt shows up.

## Where to look

- Tools: `backend/src/nexusai/modules/agent/tools.py`, `work_tools.py`
- Prompts: `backend/src/nexusai/modules/agent/prompts/system.md`, `session.md`, `daily-prep.md`
- Matters and the brief: `modules/agent/matters.py`, `briefs.py`; Today: `today_view` and `matters_brief` in `modules/agent/module.py`
- Citations: `modules/agent/citations.py`, `sources.py`; the preview: `frontend/ui/features/sources/`
- Work board: `modules/agent/channel.py` (`board`)
