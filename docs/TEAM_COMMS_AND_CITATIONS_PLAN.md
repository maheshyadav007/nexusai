# Team communication and citations: plan

Written 2026-11-17, to be built in a later session. Two pieces of work, in this order:

- **Part A. Agents that talk to each other reliably.** A question from one agent to another must always get its answer through, and a task nobody wants any more must stop.
- **Part B. Citations everywhere, with one quick preview.** Anything the agents say that came from an email or a document points to it, and any reference anywhere in the app opens the same quick preview.

## How to pick this up

- Branch `team-ask-fix`, made from `main` at `2c49615`.
- **Part A, A1 to A11, is already written on that branch, uncommitted.** The 38 team tests and the new monitor test pass. The full suite has **not** been run since these changes.
- First steps in the new session:
  1. Read this file and `git diff` on the branch.
  2. Bump `HARNESS_VERSION` in `backend/src/nexusai/modules/agent/runtime.py` to `2026.11.4`.
  3. Run the full check: `cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run lint-imports && uv run pytest -q && uv run pytest -q -m speed`.
  4. Commit Part A, then carry on from "Part A, still to do".

### Rules that apply throughout

- **No real-model evals without asking.** They spend the person's ChatGPT allowance. Fake-model tests are always fine.
- **Never delete anything on Google's server.**
- **Throwaway Homes share the Keychain.** Set `NEXUSAI_SECRETS_TEST_FILE` on scratch servers.
- **UI: no hard-coded values.** Colours, sizes and layers come from theme tokens.
- **UI: one door for components.** A building block is chosen once in `ui/primitives` and used everywhere, so it's replaced by editing one file.
- **Prompts are short and sectioned.** An important rule gets its own `## ` section. Mark a section that needs a tool with `<!-- needs: tool -->` (see `prompts_builder.for_tools`).
- **Work in small steps,** each with fake-model tests, then the full check, then a commit.

---

# Part A. Team communication

## Goal

When one agent asks another a question, the question reaches the right agent once. The answer, from the agent or from the person, always reaches the asker, and the work carries on. A task that's paused, overdue or cancelled stops cleanly, the right people are told, and no run spins on in the background.

## Background: how it works

All of this is in the Home database, `~/NexusAI/system/nexusai.db`.

| What | Table | Key fields |
|---|---|---|
| Each hand-over | `team_tasks` | `state` (queued, working, input_required, reported, blocked, verified, rejected, failed, canceled), `wake` (`owner` or `assigner`: who must run next), `owner_session`, `assigner_session`, `due`, `lease_until`, `failure` |
| Messages on a task | `agent_channel` | `kind` (assign, ask, answer, note, report, verify, reject, cancel), `sender_agent`, `recipient_agent`, `read_by` |
| Questions to the person ("Waiting on you") | `channel_messages` | status open, answered, dismissed |
| A run in progress | `agent_turns` | `closed = 0` while it runs or is paused |
| A paused run's saved state | `checkpoints.db` | resumed when the person answers |

**The cycle:**
1. A tool call (`team.py`: `_assign`, `_message_on`, `_close`) changes `state` and sets `wake`.
2. The trigger loop (`triggers.py`, `_start_tasks`) checks for tasks with `wake` set.
3. It starts the owner's run (`_wake_owner`) or the giver's run (`_wake_assigner`). Neither starts while that session already has a run going (`active_turn`).
4. Posty also waits up to `team.assign_wait_seconds` (90) inside `team_assign`, through `team.await_result`, so quick results come back in the same turn.

Run timers, all in `defaults.toml` under `[team]`:
- `task_due_minutes = 60`: an unanswered task blocks after this.
- `lease_seconds = 900`: a working task whose run is gone goes back in line.
- `silence_minutes = 20`: a working run with no new step is stopped (`monitor._silence`).
- `ping_pong_messages = 8`: asks and answers on one task before it pauses.
- `messages_per_pair_per_hour = 30`.

## The incident that started this (task 2)

Posty handed a task to the Organizer, and the Organizer needed a decision.

| Organizer's run | Posty |
|---|---|
| `team_message` ask; told "Asked. End this run now"; didn't stop | Got the question; asked the person |
| | Sent the answer: "Answered. They carry on in their own run" |
| Never saw the answer; asked again (6 times) | Tried `verify`, then `report`; both refused |
| | Saw the question again in `team_inbox`; answered again |
| 7th ask refused: "back and forth too often… paused" | |
| Tried `team_close` report: refused, task blocked or canceled | Most likely canceled task 2 |
| Kept going for ~80 calls, every call refused, until a hard limit | |

**Root cause:** a running run never received an answer. `take_notes` added only `kind = 'note'` messages to a running run. Answers waited for the next run, and the next run never came, because the asker's run didn't end; it was waiting for the answer. A team `ask` is an ordinary tool, so the agent loop calls the model again straight away. Unlike `ask_user`, nothing pauses the run.

**Made worse by:**
- Repeat asks were accepted and counted toward the loop limit.
- The loop pause told nobody and stopped nothing.
- Cancel didn't stop the run.
- Refusals from team tools ("Not sent", "Task 2 is canceled…") were recorded as successful calls, so neither the "3 refusals in a row" stop nor the repeated-call warning fired.

## Part A, done on `team-ask-fix` (uncommitted)

| # | Problem | Fix | Where |
|---|---|---|---|
| A1 | Answers never reach a running run | `take_notes` delivers `kind IN ('note','answer')`, labelled by kind | `team.take_notes` |
| A2 | Asking doesn't end the asker's run; cancel and pause don't stop it | New `TaskOver` middleware: before each model call, ends the run when its task isn't queued or working (`team.run_should_end`) | `context.TaskOver`, `team.run_should_end`, wired in `runtime._agent` via `task_over=` |
| A3 | Repeat asks accepted and counted | An ask while already `input_required` returns "Already asked…" and isn't recorded | `team._message_on` |
| A4 | Answer refused if the question came back as a report, or the task went overdue or paused | `answer` accepted on `input_required`, `blocked` and `reported`; reopens to working, clears `failure`, resets `due` | `team._message_on` |
| A5 | A reply sent as `note` to a question is ignored | A note from the giver on an `input_required` task counts as the answer | `team._message_on` |
| A6 | After answering, Posty tries `verify` and `report` | Answer reply says "Don't verify or report it: wait for their report", then waits like a hand-over (`team.wait_for`) | `tools.team_message`, `team.wait_for` (split out of `await_result`) |
| A7 | Loop pause tells nobody | `_pause_for_loop` notifies the person and sets `wake = assigner` | `team._pause_for_loop` |
| A8 | Cancel doesn't stop the run | Covered by A2 | |
| A9 | Team refusals not recognised | Team refusals start "Not sent:" or "Not done:", and both prefixes are added to `REFUSED_START` | `team.py`, `tool_errors.REFUSED_START` |
| A10 | A task run waiting on the person (approval or `ask_user`) is killed after 20 minutes as "no progress" | `_silence` skips sessions with `status = 'waiting'` | `monitor._silence` |
| A11 | Organizer prompt says to report when unsure | It says to ask once; the run ends there and the answer starts a new one. `contract_text` says the same | `prompts/organizer.md`, `team.contract_text` |

**Tests added:**
- In `tests/test_team.py`:
  - `test_asking_ends_the_run_and_the_answer_starts_the_next`, run with both `answer` and `note`. It replays task 2.
  - `test_an_answer_to_a_question_that_came_back_as_a_report_reaches_the_agent`.
  - `test_canceling_a_task_ends_the_run_doing_it`.
  - `test_an_answer_reaches_a_run_that_is_still_going`.
  - `test_a_loop_pause_tells_the_person_and_the_giver`.
  - `test_the_owner_can_never_verify_its_own_work`, updated: the run now ends at the report.
- In `tests/test_monitor.py`: `test_a_task_waiting_on_the_person_is_not_silent`.

## Part A, the rest (done)

A1–A11 were committed as `d4bb3e9`. Then:

| # | Problem | What was built | Where |
|---|---|---|---|
| A12 | `reject` closed the task for good; a weak giver rejecting expects a redo | The first reject (a reason is required) sends the task back to working with `wake = owner`; the new run's contract starts "Your report was sent back: …". A second reject closes it | `team._send_back`, `team.contract_text`, `team_close` description |
| A13 | Team refusals didn't count toward "3 in a row" | `record_call` stores status `refused` when a result starts "Not sent" or "Not done". Argument errors still count as done, so the model can fix them | `tools.record_call`, `tools.NOTHING_DONE` |
| A14 | A question or report for a closed giver chat was dropped | The giver carries on in a new chat (`assigner_session` moves there) and the person is notified with a link | `triggers._reopen_giver` |
| A15 | Four genuine rounds of questions paused a task | A3 stops repeat asks, so the limit now counts real rounds: `ping_pong_messages` 8 → 12 | `defaults.toml` |
| A16 | No eval for asking | 3 cases in group `team` in `team_b5g.json`, graded by a new `team` check (`_team_flow`): ends verified, or waits on the person's answer; at most one ask per task; a report follows any answer. The eval can't answer the person's questions, so waiting on the person passes. **Not run on a real model yet: ask first.** | `evals/team_eval.py`, `evals/team_b5g.json` |

Tests: `test_team_tools_refused_again_and_again_stop_the_run`, `test_the_first_reject_sends_the_work_back_and_the_second_closes_it`, `test_a_report_to_a_closed_chat_carries_on_in_a_new_one`.

**Done when:**
- The task 2 scenario can't loop: one ask, one answer, carry on.
- A pause, overdue or cancel stops the run and someone is told.
- The full check is green.

---

# Part B. Citations and one quick preview

## Goals

1. **Every statement that comes from an email or a document carries a citation,** in chat answers, the morning brief, tasks, reminders, "Waiting on you", team reports, everywhere. People can always check where something came from.
2. **One quick preview, everywhere.**
   - Clicking any reference anywhere in the app opens the same quick preview, over the page. It works for mail and documents, and is built so new kinds can be added (task, reminder, calendar event…).
   - The preview has a link to jump to the real email or document.
   - Cmd/Ctrl-click jumps straight there.
3. **The preview never closes the chat.** It opens on top.
4. **Modular, so it stays correct.** One source model in the backend, one registry and one component in the frontend. Adding a kind, or changing how previews look, is a change in one place.
5. **Citations can't be invented.** A marker for something no tool showed in that run is dropped, and titles always come from the database, never from the model.

## What exists today

**Backend: `backend/src/nexusai/modules/agent/citations.py`**
- `agent_turn_sources` records what a tool handed the model in the open turn.
- The model writes `[mail:123]` or `[doc:KEY#p3]`. `Citations.rewrite` turns markers into `[1](#cite-1)` and drops any for things not read. `Citations.part()` builds the sources list for the message.
- This runs only on chat replies, set up in `runtime.py` with `citations=citations.Citations(self.ctx, turn)`.

**Frontend**
- `ui/primitives/Citation.tsx` has `CitationMark` (the number) and `SourcesPill` (the "N sources" list).
- `ui/features/assistant/Markdown.tsx` renders `#cite-N` links as citation numbers when given `sources`.
- `ui/features/assistant/MessageSources.tsx`: `useOpenSource()` opens mail with `preview.showThread(id)` and documents with `preview.show({key})`.
- `ui/features/documents/DocumentPreview.tsx`:
  - `DocumentPreviewProvider` shows documents in `PreviewPanel` and mail in a `Dialog` wrapping `ThreadScreen`. The preview already has "Open message" and "Open full" links.
  - `PreviewInApp` is the fallback for the quick-ask window, where references open in the app.

## What's wrong (findings)

**Agents rarely cite:**
1. **Weak, scattered instructions.**
   - `prompts/session.md`, "## Citing what you read", says "Put a marker…", not "always". It sits after the team rules.
   - `prompts/daily-prep.md` has one bullet: "Cite mail as [mail:ID] only after reading it."
   - The Organizer, the Mail agent's chat and `system.md` say nothing.
2. **The model has to translate ids.**
   - Tools print `[thread 123]`: `tools.py` search output, `mail_agent._plate_lines`, the digest in `mail_agent`, and `work_tools.py`.
   - The marker must be `[mail:123]`, and a small model skips or fumbles the conversion.
3. **Most of what the Brief writes about isn't citable.** Only these record a source:
   - `search_mail` and `read_thread` in `tools.py`;
   - `search_documents` and the document read in `tools.py`;
   - search by meaning in `work_tools.py`.

   Not recorded: `read_plate`, the plate in the morning brief message, `list_mail`, `list_tasks`, `list_reminders`, `read_work_board`, and team reports. Markers for those threads are silently dropped.
4. **The brief loses its citations.**
   - `briefs.save` (the `update_brief` tool) stores raw text.
   - `module.py` serves it as `prep_text`, and `TodayScreen.tsx` renders `<Markdown text={data.prep_text} />` with no sources.

**The preview closes the chat:**
- `DocumentPreviewProvider` calls `setNeedsRoom(Boolean(target) || thread !== null)`.
- `AssistantProvider.tsx` implements it as `if (needed) setWanted(false)`: the chat closes and never reopens. The preview is the only caller.
- Layers: the `Dialog` overlay is `z-40` (`ui/primitives/Dialog.tsx`), and so is the chat dock (`AssistantDock.tsx`). The preview wins only because it's added to the page later.

**Many places skip the preview** and link straight to the Mail page:
- `ui/features/today/TodayScreen.tsx`: thread rows (`/mail/all/${thread.id}`), the question rows' "Open source", and due items through the `DueItem.link` string.
- `ui/features/today/MailOrganizationCard.tsx`.
- `ui/features/planner/TasksScreen.tsx` and `RemindersScreen.tsx` ("Open source" link).
- `ui/features/assistant/Cards.tsx`, `ui/features/agent/AgentKnows.tsx`, `ui/features/mail/ThreadRowView.tsx`, `threadActions.ts`.

**The data has no source field:**
- `DueItem` has `link: str`.
- Proposals in "Waiting on you" have no source.
- Tasks and reminders have only `thread`, and can't point to a document or to one message in a thread.

## Design

### B1. One source model (backend)

- A contract `Source` in `contracts/`:
  - `kind`: `"mail" | "doc"`, extensible;
  - `ref`: thread id or document key;
  - `message`: optional, one message in a thread;
  - `page`: optional;
  - `title`, `detail` (sender or folder), `date`.
- One resolver, `sources.describe(kind, ref, ...) -> Source | None`. It lives in a small module, grown out of `citations.part()`. Titles and senders always come from the database.
- Every API item that came from mail or a document carries `source: Source | None`:
  - Today: `TodayThread`, `DueItem` (replacing `link`), "waiting on you" questions and proposals;
  - tasks and reminders;
  - team reports;
  - the brief, as `prep_sources: list[Source]`.
- Tasks and reminders get an optional document source, not only `thread`, through a migration.

### B2. One preview (frontend)

- **A new feature module, `ui/features/sources/`:**
  - `registry.ts` maps each kind to `{ icon, label, Preview component, fullHref(source) }`. Mail and documents are the first two entries. Adding a kind is one entry.
  - `SourcePreviewProvider` replaces `DocumentPreviewProvider`'s two branches. It opens any `Source` through the registry and keeps the "next/previous" list behaviour.
  - `useOpenSource()` moves here from `MessageSources.tsx`.
  - `PreviewInApp` stays as the fallback for the quick-ask window.
- **One primitive, `ui/primitives/SourceRef.tsx`, plus the existing `CitationMark`:**
  - **Hover:** a tooltip with title, sender and date.
  - **Click:** opens the quick preview.
  - **Cmd/Ctrl-click:** goes to `fullHref`.
  - **Space on a focused reference:** opens the preview, like macOS Quick Look. Esc closes it.
- **Exact message:** the mail preview opens on the cited message and highlights it. Documents open on the cited page.
- **A guard test** fails if a new direct link to `/mail/all/` or `/mail/thread/` appears outside the registry and the Mail screens.

### B3. Preview and chat

- The preview stops calling `setNeedsRoom`.
- A theme layer token puts the preview above the chat dock, with the token defined in the theme, not a number in a class.
- **Opening an email from a mail list (a category, a folder, All, search) still collapses the chat,** so the email has room to be read. This is what collapsing was built for, and it stays.
- **One rule makes room, nothing else.** Today three separate pieces of code close the chat:
  1. `setNeedsRoom(true)`, which is just `setWanted(false)` under another name; only the preview calls it;
  2. `ThreadRowView.tsx` calling `assistant.setOpen(false)` on a row click;
  3. the address rule in `AssistantProvider.tsx` (`READING`): opening `/mail/…/<id>` or `/search/<id>` closes the chat.

  Keep only 3. Remove `setNeedsRoom` completely (the provider, the `Assistant` type and `DocumentPreview.tsx`), and remove the `setOpen(false)` from the row click. `setOpen` stays for the person's own open and minimize buttons.
- **`setOpen` is the one switch.** How to keep it that way:
  - Rules that make room live in one list inside `AssistantProvider`, and each calls `setOpen(false)`. Components never close the chat to make room themselves; they call `setOpen` only for something the person clicked (open, minimize, "Ask agent").
  - A rule fires once, when something happens (a page change), and never holds the chat shut while a condition is true, so it can't fight the person's own open button.
  - Nothing brings the chat back by itself today. If that's wanted later, the provider also remembers *why* it closed (the person, or a rule), and nothing that calls `setOpen` changes.
- Tests:
  - The chat open, a preview opened and closed: the chat is still open with its draft intact.
  - The chat open, an email clicked in a category list: the chat collapses and the email opens.

### B4. Make agents cite (prompts and harness)

1. **Tool output prints the marker itself:**
   - `[mail:123]` instead of `[thread 123]`, everywhere a tool lists mail: search, plate, digest, `list_mail`, tasks, reminders, the work board, team reports;
   - `[doc:KEY]` for documents.

   The model copies it as written. This is the biggest lever for a small model. Update tests that assert `[thread …]`.
2. **Anything a tool showed in this run can be cited.** Every tool above calls `citations.note` for each item it lists. Opened versus only listed still decides what appears under "read" in the sources list.
3. **One firm section in `prompts/system.md`, shared by every agent:**

   ```
   ## Cite what you say

   - Every statement that comes from an email or a document gets its marker straight after it, such as [mail:123] or [doc:KEY]. Copy the marker exactly as the tool showed it.
   - This applies everywhere you write for the person: replies, the brief, reports and summaries.
   - Never cite something no tool showed you in this run, and never write a list of sources yourself.
   ```

   Remove the overlapping lines from `session.md` and `daily-prep.md`. Keep only their specifics, such as `#page` in `session.md`.
4. **The harness enforces it, once, like the memory nudge (`context.PromisedMemory`):**
   - **Chat:** a new `after_model` middleware. If the run has sources in `agent_turn_sources`, the final reply is more than a sentence, and it contains no marker, send it back once: "You used mail or documents but cited none. Add their markers and reply again."
   - **Brief:** `update_brief` checks the bullets. If a bullet names a thread from the plate (by subject or sender) and has no marker, it returns "Not saved: these bullets need their [mail:ID] markers: …". Once per run, so a second attempt is always saved.
5. **The brief keeps its citations.** `briefs.save` rewrites markers with `Citations` for that run's turn, and stores the text with `#cite-N` links plus the sources list. Today renders it with `Markdown` and `SourcesPill`.

### B5. Today page

| Item | Today | After |
|---|---|---|
| Morning brief | Raw text | Citation numbers, plus "N sources" under it |
| Needs reply / to chase rows | Link to Mail page | Click opens the preview; "Draft reply" stays |
| Due today (tasks, reminders) | `link` string | Source chip, preview |
| Waiting on you: agent questions | "Open source" link | Source chip, preview |
| Waiting on you: proposals | No source | Source chip; the backend carries the source of each proposal |
| Mail organisation card | Link | Source chip where it names a thread |
| Since you looked | Counts | Unchanged: there's no single source |

### B6. Rest of the app

The same chip in Tasks, Reminders, cards in chat, team reports in the channel, Agent knowledge (memory notes ending in `[mail:123]`), notifications that name a thread, and the approval preview.

### B7. Checks

**Fake-model tests (backend):**
- The brief keeps its citations, and a marker for something never shown is dropped.
- Plate items are citable.
- The chat nudge fires once and only once.
- The `update_brief` check refuses once, then saves.
- `Source` is filled for each Today item.

**Frontend tests:**
- The registry opens mail and documents.
- Cmd/Ctrl-click goes to the full page.
- The guard test against direct links.
- The preview doesn't close the chat.

**Real checks:**
- With permission only, a 6 Luna run: the share of chat answers and brief bullets that cite, using the existing `cites` check in `backend/evals/team_eval.py`.
- Then a real brief on the person's Gmail.

**Done when:**
- A morning brief on real mail cites every bullet that came from an email.
- Every reference on Today, Tasks and Reminders opens the same preview without closing the chat.
- No direct mail links remain outside the registry.

## Order of work

1. **Part A:** commit A1–A11, then A12–A15 as the person decides.
2. **B1 + B2 + B3, the foundation, in one step:**
   - the `Source` contract and resolver;
   - the sources registry, provider and `SourceRef`;
   - the preview no longer closing the chat;
   - chat citations moved onto it, with no behaviour change.
3. **B4:** marker output, citable listings, the `system.md` section, the nudges, brief citations.
4. **B5:** Today.
5. **B6:** the rest of the app.
6. **B7:** the real-model check (ask first), then real Gmail.
