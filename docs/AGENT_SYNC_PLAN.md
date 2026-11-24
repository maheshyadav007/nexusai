# Posty sees what the app shows

Planned 2026-11-24, revised the same day after a review against the code, and built the same day: each step below was built, tested and committed on its own, in order. The tests are in `backend/tests/test_agent_sync.py`. Not yet tried on the real account with the real model.

## Why

Asked "What needs me today?", Posty took 14 steps: it read the work board, listed open tasks and reminders, and searched mail four times. It never looked at a matter. It then said the first RCA for Carrier X was overdue, when that task had been ticked at 21:45.

The cause isn't one bad answer: **the app and Posty have two different pictures of the person's work.** Today is built from matters. Posty rebuilds its picture from mail and older lists, and the chat prompt tells it to read the work board first (`prompts/session.md`, "How to work", step 1). A deadline on the board stays open after its task is ticked, so the board can say something is overdue that's done.

## What's wrong today

Found by reading the code on 2026-11-24.

1. **No way to see all matters.** `read_matter` (`modules/agent/tools.py`) opens one matter, only by number. Nothing lists them. `read_plate`, the one tool with the whole picture, is limited to the brief agent (`BRIEF_AGENT_ONLY`).
2. **Finished work is hidden.** `list_tasks` leaves out done tasks by default; `list_reminders` leaves out ones that went off (`work_tools.py`). An email still reads as an open ask after the work is done.
3. **Mail results don't say where things stand.** `search_mail` and `read_thread` say nothing about their matter's state or work.
4. **Two records of the same work.** The work board (`work_board` table, `channel.board`) holds deadlines that overlap tasks. `session.md` and `mail.md` send agents to it first.
5. **No prompt rule on where to start** for questions about the day or about how something is going.
6. **No agent is told how NexusAI organizes work:** what a matter is, what it owns, links, states, kept vs suggested.
7. **Citations cover only mail and documents.** `citations.MARKER` knows `mail` and `doc`; `sources.describe` the same.
8. **Addresses are mixed and sometimes raw.** `read_thread` prints `read_document key m:12:2`; `list_tasks` prints `88: title`; `read_matter` prints `open task:88` and "related matter 7"; the plate prints matters as `[12]`.
9. **Three builders of the same day.** `briefs.snapshot` (old, still names the work board), `matters.plate` with `mail_agent.brief_task` (the brief's), and `matters.brief` (Today's list). They can drift apart.

## Decisions

- **One builder of the day.** `matters.plate` is the day as matters, and it builds Today's list's data too (`matters.brief` and the plate read the same `_matters` rows). `briefs.snapshot` is removed; its one caller uses `brief_task`.
- **"Your day" is in front of Posty on every chat message**, as a prompt layer after the stable ones and before "This run", so it doesn't break the cached prefix or pile up in history. It's built fresh for each run.
- **Untrusted content:** "Your day" holds titles, states, dates and the one-line "why" of the latest email, never an email's body. It's wrapped in `<untrusted>` as data and doesn't mark the chat untrusted, the same as `read_matter` and `list_tasks` today. Reading an email still marks it.
- **Addresses come from `kinds.py`.** It already names every object `kind:id`. In text for a model, an object is written in brackets: `[matter:12]`, `[task:88]`, `[reminder:5]`, `[mail:123]` (a conversation), `[doc:KEY]`. Home files are documents (`doc:h:N`), so there's no separate file kind.
- **One address is also the citation**, for every kind above.
- **The object model is shared.** It goes in `system.md`, which every agent gets, kept short (about 150 words) because the mail agent runs it on every email. Where to start and how to answer stay in each agent's own prompt.
- **Tools:** `open_item(address)` opens any object with its owner, state and links. `find_matters(words, state)` lists matters. They replace `read_matter`; `read_work_board` goes with the board. `read_plate` stays as the brief agent's own tool, for a run that wasn't handed the plate; it returns the same plate. `list_tasks` and `list_reminders` stay, as lists for the organizer, with addresses and the last two days of finished work.
- **The work board is retired.** Open deadlines become due dates on tasks; the board tools go.
- No real-model evals without asking first; fake-model tests are fine.

## The object model every agent is taught

- **Email → conversation → matter.** A matter is one real thing going on, however many conversations it took.
- **Ownership is a tree.** A matter owns its conversations, tasks (with their reminders) and files.
- **Links for the rest:** related matters, merged ones, files used from elsewhere. When it's unclear whether two belong together, the person decides.
- **States:** waiting on you, waiting on others, worth knowing (fyi), done. Code works them out; agents don't set them by hand.
- **Kept vs suggested.** Only what the person kept is theirs. A suggestion waits for their decision. "Looks done" means a later email shows it finished; the person confirms.
- **Addresses:** the table above, used to open, cite and act.

## Steps

### 1. Citations for every kind, and no raw keys

- `MARKER`, `PARTIAL` and `sources.describe` cover `matter`, `task` and `reminder`. Titles come from the database.
- On screen they use today's chip: a matter opens its page on Today, a task or reminder opens its matter if it has one, otherwise Tasks or Reminders.
- Before an answer is shown, a bare key outside a marker (`m:12:2`, `task:88`) is dropped.
- **Done when:** a test answer citing a matter and a task shows two numbered sources with their real titles, and a bare key never reaches the screen.

### 2. "Your day" in front of Posty

- `matters.plate` writes matters as `[matter:12]`, and adds "Done since yesterday" and "Waiting for their decision" (suggestions and looks-done). `brief_task` uses it as now.
- Chat runs get it as the "Your day" layer. Its markers count as shown for the turn, so Posty can cite them.
- `briefs.snapshot` is removed.
- **Done when:** a test sees the layer in what the model is sent; a ticked task shows under done, not open; and the plate lists the same matters, waiting on you and on others, as Today.

### 3. Addresses everywhere

- Every tool prints objects only by address: `list_tasks`, `list_reminders`, `read_thread` (attachments as `[doc:KEY]`), matter lines.
- `search_mail` and `read_thread` add where a conversation stands: `[matter:12] done · [task:88] done 21:45`.
- `list_tasks` and `list_reminders` include what finished in the last two days, marked done.
- **Done when:** tests show those outputs carry addresses and a ticked task, with no bare ids.

### 4. The object model in `system.md`

- The section above, short, in the shared prompt. Its lists of states and kinds are checked against `contracts` and `kinds.py`.
- **Done when:** a test fails if the prompt and the code's lists disagree.

### 5. `open_item` and `find_matters`, and where to start

- `open_item` takes any address and shows the object, its owner, state, work, links and recent history, each as an address. `find_matters` lists matters by words and state.
- They replace `read_matter` in every tool set.
- `session.md`: for the day, answer from "Your day"; for how something is going, open that matter; search mail only for what those don't cover. Answers about the day take the brief's shape, one cited line per matter.
- **Done when:** a scripted chat opens a matter and a task by address, and the prompt names no retired tool.

### 6. One record of the work

- A migration turns open board deadlines into due dates on their conversation's open task, or into new tasks, and closes them on the board.
- `read_work_board` and `write_work_board` go; prompts that name them change. The `deadline` kind goes from `kinds.py`, matters, Today and the overdue check.
- **Done when:** a test with an old board deadline sees a dated task after migrating, and no tool or prompt names the board.

### 7. Staying in sync

- The agent monitor (`monitor._detours`) flags a chat run about the day whose first step was a mail search. It's kept on the Agents page as a "detour" alert and never notifies, since it's for tuning the agents. The day-question words are used only for this check, never to route.
- The tests from steps 1–6 stay as the guard.

## Where to look

- Tools: `backend/src/nexusai/modules/agent/tools.py`, `work_tools.py`
- Prompts: `modules/agent/prompts/system.md`, `session.md`, `daily-prep.md`, `mail.md`
- Matters and the plate: `modules/agent/matters.py`, `kinds.py`, `links.py`; the brief: `mail_agent.brief_task`, `briefs.py`
- Layers: `modules/agent/prompts_builder.py`, `knowledge.layers_for`, `runtime.py` (where "This run" is added)
- Citations: `modules/agent/citations.py`, `sources.py`, `ui_stream.py`; on screen: `frontend/ui/features/sources/`
- Work board: `modules/agent/channel.py` (`board`), `scheduler.py` (overdue check)
