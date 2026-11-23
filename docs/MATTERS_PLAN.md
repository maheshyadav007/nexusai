# Matters: one record for each real thing going on

Status, 2026-11-21: reviewed and kept, except the graph view (dropped). **Built on the `conversations` branch:** phase 1 (resends join, one task per conversation, Done closes the work), phase 2 in a lean form (`modules/agent/matters.py`: `matters`, `matter_threads`, `matter_events`; state, due, people and work are read from the conversations each time instead of stored; code-only links by shared id or same sender and subject; rule-filed mail can join but never start a matter; one-time backfill), and phase 6's Today as three tabs: **Brief** (the day's changes, marked when unseen, plus matters by who moves next), **Week** (one lane per matter) and **Matters** (list and timeline, Done with Undo, Not part of this). Next: phase 3 (the model picks from the candidates), then `matter_people`, `matter_relations` and `brief_lines`. Read section 0 first if you are picking this up in a new session.

> **The idea.** The person doesn't care about emails. They care about the *things going on*: Priya's budget decision, the Q4 timesheet, the visa renewal, the PLM release. Today NexusAI tracks emails and threads, so the same thing arriving as three emails becomes three things: three tasks, three reminders, three brief lines. This plan adds one durable record per real thing, a **Matter**. Every email, thread, task, reminder, draft and brief line attaches to it, and every change to it is logged with the email that caused it. The inbox stays for reading mail; Today becomes a live board of matters.

---

## 0. Picking this up in a new session

1. Read this whole file, then `docs/MAIL_ORGANIZATION.md` (the sorting engine that runs before the AI) and `docs/AGENT_CONTEXT_AND_PROMPTS.md`.
2. Memory rules that apply (see `~/.claude/projects/.../memory/MEMORY.md`):
   - **Mail is the product.** Judge Mail agent changes on the real mailbox, not only on tests.
   - **No real-model evals without asking.** Tests with the fake model are free.
   - **Throwaway Homes share the Keychain.** Set `NEXUSAI_SECRETS_TEST_FILE` on scratch servers.
   - **Harness for a weak model.** Small prompts, closed choices, helpful errors.
   - **Keep it simple.** One phase at a time, each shippable on its own.
   - **One door for components.** Use the existing primitives; no hardcoded styles.
3. Start with **Phase 1** (section 15). It needs no new concepts and ends the duplicate tasks people see today.
4. Every phase lists its files, tests and acceptance checks. Don't start the next phase until the current one passes its check on real mail.

---

## Object model (built 2026-11-22)

- **Ownership is a tree:** a task's matter is `tasks.matter`, a reminder's parent is `reminders.task` or `reminders.matter`. Every task from mail keeps `tasks.source_message`, the email that asked for it.
- **Every other link** is a row in `links` (`modules/agent/links.py`): related, merged, uses. Links are ended with a reason, never deleted.
- **Kinds** are declared once in `modules/agent/kinds.py`; objects are named `task:88`, `thread:12`, `doc:5` on screen, in prompts and in links.
- **Children follow their parent** (planner `_children_follow`): a task's reminders close, reopen and move with it.
- **Siblings are asked:** `matters.related` lists the rest of the matter after something finishes; `matters.closeItems` closes what the person ticks and remembers what they kept (`matter_kept`). The sheet is `RestOfMatter.tsx`, triggered from the shared task and status hooks. An agent that finishes a task only tells the person what's still open.
- **The AI sees related matters** (`matters.context_for`) and may pick one by number (`record_triage.matter`, checked against the shortlist) and point a task at the open one it updates (`tasks[].updates`). A shared sender alone shows a matter to the AI but never joins or relates it by code.
- **Timeline** pages oldest first (`matters.get` gives the newest page, `matters.events` the ones before it).

## 1. What "best mail app in the world" means here

These are the outcomes. Every design choice below should make at least one of them better, and none worse.

| Outcome | How we'll know |
|---|---|
| **Nothing that matters slips.** | Every email that needs the person is linked to an open matter, or explicitly marked done. Measure: open asks with no matter = 0. |
| **Nothing shows up twice.** | One real-world thing equals one matter, with at most one open task per action. Measure: duplicate task rate on the real mailbox, before vs after (target: under 2%). |
| **One glance tells you what's going on.** | At any hour, the brief and Today reflect every important email that has arrived. Measure: brief staleness, meaning minutes from an important email arriving to its brief line updating (target: under 2 min). |
| **Closing one thing closes everything about it.** | Replying, finishing a task or dismissing a reminder offers to close the related open items in one tap. Measure: share of related items left open 24 h after their matter closed. |
| **You can always see why.** | Every task, reminder, brief line and link shows the email it came from and the reason. Measure: 100% of items have a source in the matter timeline. |
| **It runs on a weak model.** | The AI step is a choice from a small list, checked by code. Measure: share of AI answers refused by the validator, and the duplicate rate on the smallest model we support. |

---

## 2. Where things stand today

### The pipeline

```
IMAP / PST ──► store_message ──► rule engine (rules.Engine.decide)
                                   ├─ kept from the AI → Automated/… folders, done
                                   └─ reaches the AI ──► mail.needsTriage
                                                          └─► Mail agent: one run per thread
                                                              task_for() builds the prompt
                                                              model calls record_triage
                                                              Triage._apply writes status, importance,
                                                              tasks, reminders, draft, folders
Brief: daily-prep schedule ──► brief_task() ──► update_brief (whole text, once a morning)
```

### Why duplicates happen (verified in code, 2026-11-21)

1. **A reminder email starts a new thread.** `store._assign_thread` joins by References, In-Reply-To, Outlook Thread-Index, and by subject only when the subject has a reply prefix (`Re:`). "Reminder: complete training", or the same subject sent again without `Re:`, becomes a new thread.
2. **The agent is shown open work for that thread only.** `mail_agent.task_for` adds `SELECT … FROM work_board WHERE thread = ? AND done = 0`, so the task made from the first email is invisible when judging the reminder.
3. **The duplicate check is per thread.** `planner.has_task(db, title, thread)` compares titles only within the same thread (fuzzy), and `planner.has_reminder` compares exact titles within the same thread.
4. **The brief is rewritten whole, once a morning** (`prompts/daily-prep.md`, `mail_agent.brief_task`). An important email at 11:00 isn't in the brief until the next morning, unless someone asks.
5. **Nothing connects related items.** Closing a task doesn't touch its reminder, the waiting status of the other thread, or the brief line.

### Seen on the real mailbox (2026-11-21, read-only, no model)

- Google Cloud "verification past due" came twice, a week apart, as two threads: two tasks and two deadlines.
- "[GitHub] Please verify your device" got two open tasks in the **same** thread in different words; one title had a `[mail:15937]` marker in it.
- Every task from mail also had a work-board deadline, so Due today showed each one twice.
- The corp sample (`evals/corp_mailbox.json`) shows what only matters can fix: change 88213 arrives from Karthik, Swarm approval and Swarm comment; Carrier X and Orion each span three senders and subjects.

### What already helps

- **`rules.Engine`** decides per batch, before the AI, with a reason for each email. It's the model to follow: deterministic first, small AI step, decisions logged.
- **Semantic index** (`modules/semantic`) for meaning similarity.
- **`textmatch.same`** for fuzzy titles.
- **`signals.about_thread`** for counted facts (who they write to, To vs Cc).
- **`parse.tags_of`** for subject tags like `[PLM-1104]`.
- **Team channel and work board** (`agent/channel.py`) and the **brief agent** with `update_brief`.

---

## 3. The model: Matters

### 3.1 What a matter is

A **matter** is one real-world thing the person may need to know about or act on, with a beginning and an end.

| Is one matter | Is not one matter |
|---|---|
| "Q4 timesheet": the HR ask plus 2 reminders plus your reply | Every email from HR |
| "Priya's budget decision": the ask, your question, her follow-up, a meeting invite | Everything with Priya |
| "PLM ECO-1104 release": the notification you were named in, plus the discussion thread | All PLM mail (that's a folder) |
| "Visa renewal": the embassy email, a reminder, the appointment confirmation | "Travel" (that's a topic) |

Rules of thumb:
- A matter ends. A folder or topic doesn't.
- A matter has at most one owner of the next move: you, someone else, or nobody (done).
- Mail kept from the AI never creates or joins a matter, and a conversation filed there later leaves its matter (it comes back if moved out). Since 2026-11-23 nothing in such a folder reaches the AI, including mail that names you.

### 3.2 Terms

- **Thread:** what we have today, joined by headers. Unchanged.
- **Link:** a thread belongs to a matter. One matter can have many threads. A thread belongs to at most one matter at a time (it can move).
- **Work:** tasks, reminders, follow-ups and drafts. Each belongs to a matter, and still records the thread it came from.
- **Event:** one line on a matter's timeline: what changed, when, why, and which email or action caused it.
- **Relation:** matter to matter: `same_as` (merged), `part_of`, `follows`, `related`.

### 3.3 Naming

"Matter" is the working name. The UI may call it something else; options are "Topic", "Item" or "Loop". The code uses `matter`. Decide before Phase 6 (UI). Recommendation: the UI shows just the matter's **title** and avoids naming the concept at all ("Part of: Q4 timesheet").

---

## 4. Data model

SQLite, in the mail module's database. Everything is a plain table.

```sql
-- One record per real-world thing.
CREATE TABLE matters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account TEXT NOT NULL,
  title TEXT NOT NULL,                 -- short, specific: "Q4 timesheet for HR"
  state TEXT NOT NULL,                 -- open | waiting_on_you | waiting_on_others | scheduled | done | dropped
  next_action TEXT,                    -- reply | do | decide | read | none
  due TEXT,                            -- the soonest date that matters (YYYY-MM-DD or ISO time)
  importance TEXT NOT NULL DEFAULT 'normal',
  summary TEXT NOT NULL DEFAULT '',    -- one sentence, kept current: what's going on now
  owner TEXT,                          -- who moves next when waiting_on_others (address)
  created TEXT NOT NULL,
  updated TEXT NOT NULL,
  closed TEXT,                         -- set with done/dropped
  merged_into INTEGER                  -- set when merged into another matter (kept for history)
);
CREATE INDEX matters_open ON matters (account, state, due);

-- Threads in a matter. A thread moves by updating its row; the move is logged as an event.
CREATE TABLE matter_threads (
  thread INTEGER PRIMARY KEY,          -- a thread is in at most one matter
  matter INTEGER NOT NULL,
  how TEXT NOT NULL,                   -- headers | rule | ai | person
  confidence TEXT NOT NULL,            -- certain | high | medium | low
  why TEXT NOT NULL,                   -- "Same sender, subject 92% alike, 6 days apart"
  linked TEXT NOT NULL
);
CREATE INDEX matter_threads_matter ON matter_threads (matter);

-- The timeline. Append-only, so it is also the audit trail and the undo log.
CREATE TABLE matter_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  matter INTEGER NOT NULL,
  time TEXT NOT NULL,
  kind TEXT NOT NULL,                  -- created | mail | linked | unlinked | state | due | work_created
                                       -- | work_updated | work_closed | brief | merged | split | renamed | note
  message INTEGER,                     -- the email that caused it, when one did
  ref TEXT,                            -- "task:88", "reminder:31", "thread:402", "matter:7"
  by TEXT NOT NULL,                    -- engine | agent:<name> | person
  text TEXT NOT NULL,                  -- one plain sentence for the timeline
  undo TEXT                            -- JSON describing how to reverse it, when it can be
);
CREATE INDEX matter_events_matter ON matter_events (matter, time);

-- People in a matter, and their part in it.
CREATE TABLE matter_people (
  matter INTEGER NOT NULL,
  address TEXT NOT NULL,
  role TEXT NOT NULL,                  -- asked | waiting | cc | owner | mentioned
  PRIMARY KEY (matter, address)
);

-- Matter to matter.
CREATE TABLE matter_relations (
  a INTEGER NOT NULL, b INTEGER NOT NULL,
  kind TEXT NOT NULL,                  -- same_as | part_of | follows | related
  why TEXT NOT NULL, by TEXT NOT NULL, time TEXT NOT NULL,
  PRIMARY KEY (a, b, kind)
);

-- Work joins its matter; thread stays for "where did this come from".
ALTER TABLE tasks ADD COLUMN matter INTEGER;
ALTER TABLE reminders ADD COLUMN matter INTEGER;
ALTER TABLE work_board ADD COLUMN matter INTEGER;
-- Drafts: the draft table (or threads.draft) gains matter too.

-- Per-message fingerprints, computed once at ingest, for the candidate finder (section 5.1).
CREATE TABLE message_marks (
  message INTEGER PRIMARY KEY,
  subject_core TEXT NOT NULL,          -- normalize_subject minus tags, numbers, punctuation
  ids TEXT NOT NULL,                   -- JSON: ticket ids, order/invoice-like tokens, tags
  sender_stem TEXT NOT NULL,           -- grouping._stem(sender)
  people TEXT NOT NULL                 -- JSON: from+to+cc minus the owner
);

-- The brief as lines, one per matter (section 8).
CREATE TABLE brief_lines (
  matter INTEGER PRIMARY KEY,
  section TEXT NOT NULL,               -- first | owe | due | chase | changed
  line TEXT NOT NULL,                  -- one bullet, with [mail:N] markers
  rank INTEGER NOT NULL,
  updated TEXT NOT NULL,
  seen TEXT                            -- when the person last saw this version
);
```

---

## 5. The pipeline for one email that reaches the AI

```
email ─► 5.1 fingerprints (code) ─► 5.2 certain links (code) ─► 5.3 candidates (code)
      ─► 5.4 AI decides (one call, closed choices) ─► 5.5 validator (code) ─► 5.6 apply + events
      ─► 5.7 after: brief line, cascade offers, notifications
```

### 5.1 Fingerprints (at ingest, no model)

Computed in `store_message` and saved in `message_marks`:

- **subject_core:** `normalize_subject`, then drop `[tags]`, numbers, dates and punctuation, lowercase, and collapse whitespace. "Reminder: [HR-22] Submit Q4 timesheet by 30 Nov" becomes "reminder submit q timesheet by nov". The word "reminder" stays; there are no language lists.
- **ids:** `tags_of(subject)` plus id-like tokens from the subject and the first lines of own text: alphanumerics with at least 4 digits, or `ABC-123` shapes. Language-agnostic.
- **sender_stem:** from `grouping._stem`, so `alerts@` and `alerts-eu2@` match.
- **people:** participants minus the owner.

### 5.2 Certain links (no model)

A thread joins a matter with `how = headers`, `confidence = certain` when:
- the thread already has a matter (a reply in the same thread), or
- `References`, `In-Reply-To` or Thread-Index point into a thread that has a matter.

Certain links skip the AI matching step (5.4 still decides the work).

### 5.3 Candidate finder (no model)

For an email with no certain link, score the **open and recently closed (14 days) matters** for the same account:

| Signal | Points | Evidence text |
|---|---|---|
| Shares an id token (ticket, order, invoice) | +5 | "Both mention ECO-1104" |
| Same sender (or sender stem) and subject_core word overlap ≥ 0.6 (Jaccard) | +4 | "Same sender, subject 78% alike" |
| Same sender, any subject, within 3 days, and that matter is waiting_on_you | +1 | "Same sender, 2 days after" |
| Subject_core overlap ≥ 0.8, different sender | +2 | "Subject 85% alike" |
| People overlap ≥ 2 addresses besides the owner | +2 | "Same people: Priya, Arun" |
| Meaning similarity (semantic index, own text vs the matter's latest email) ≥ threshold | +2 to +3 | "Says much the same thing" |
| Person previously moved a thread from this sender into this matter | +3 | "You put mail like this here before" |

- **Keep the top 5 with score ≥ 3.** Each candidate carries its evidence strings, title, state, due, last event, and its **open work** (tasks, reminders, drafts) with ids.
- **Auto-link without AI** when the top score is ≥ 8 *and* the second is ≤ 3 (one clear winner with an id match). Log it as `how = rule`, `confidence = high`, so the person can see and undo it.
- **Thresholds live in config** (`[mail.matters]` in `defaults.toml`), not in code, and are tuned on the real mailbox.
- **Cost:** everything is indexed; the semantic lookup runs only for the top ~20 from the cheap signals.

### 5.4 The AI step

One call per email (or per thread batch), the same run that judges importance today. The prompt has **four blocks**, always in this order:

**A. Instruction (fixed, short):**
> You keep the person's matters correct. A matter is one real thing going on. For this email: pick the matter it belongs to (or start one), then make that matter's work right: keep, update, close or create items. Never add something that already exists; update it instead. Every change needs a reason the person will read.

**B. This email:** as today (`task_for`), inside `<untrusted>`.

**C. Related matters (from 5.3):** compact, with ids the model must copy.

```
Related matters (from code; evidence is reliable, pick by id):
[m:12] "Q4 timesheet for HR" · waiting_on_you · due 2026-11-30
   evidence: same sender (hr-notify@corp); subject 91% alike; both mention HR-22
   last: 2026-11-14 "HR asked to submit by 30 Nov" (mail 341)
   open work: [task:88] "Submit Q4 timesheet" due 11-30 · [reminder:31] "Timesheet" 11-29 09:00
[m:7] "HR training compliance" · fyi · no due
   evidence: same sender
   open work: none
```

**D. Allowed actions and output contract:** `record_triage` gains a `matter` and a `work` field; the old free `tasks`/`reminders` lists stay for one release, then go.

```json
{
  "matter":  {"use": 12}   |   {"new": {"title": "…", "why": "…"}},
  "work": [
    {"op": "keep",   "ref": "task:88"},
    {"op": "update", "ref": "task:88", "due": "2026-11-28", "why": "Second reminder moved the date"},
    {"op": "close",  "ref": "reminder:31", "why": "Replaced by the new date"},
    {"op": "create", "kind": "task" | "reminder" | "follow_up",
                     "title": "…", "due": "…", "why": "…"}
  ],
  "matter_state": "waiting_on_you" | "waiting_on_others" | "done" | "fyi",
  "matter_summary": "One sentence: what's going on now.",
  "brief": {"op": "none" | "update" | "add", "line": "…"}
}
```

Rules in the prompt, short and testable:
- If a related matter is about the same thing, **use it**, even if the subject differs.
- A reminder email **updates** existing work (due date, urgency); it never creates a second copy.
- `create` only for an ask that no open item covers.
- `close` only with a reason that comes from this email ("they say it's done", "replaced by …").
- For mail that needs nothing (fyi, low), `matter` may be omitted. No matter is created for it.

### 5.5 Validator (code; the safety net)

Runs on the AI's answer before anything is written. It turns mistakes into fixes or clear refusals:

| Check | Action |
|---|---|
| `use` id not in the candidates offered | Refuse: "m:44 wasn't offered. Pick one of m:12, m:7, or new." The agent retries once. |
| `ref` not open work of the chosen matter | Refuse with the list of valid refs. |
| `create` whose title fuzzily matches open work on the chosen matter (`textmatch.same`) or on any candidate with score ≥ 6 | **Turn it into `update`** of that item, and log "merged with task:88". |
| `new` matter while a candidate has score ≥ 8 | Keep `new`, but add a `related` relation and flag the matter for review ("Possibly the same as Q4 timesheet"). It's shown to the person, never silently merged. |
| `close` without a why | Refuse. |
| Dates in the past or unparseable | Drop the field, and keep the rest. |
| More than 3 creates from one email | Keep 3; log the rest as a note. |

Errors are short sentences the model can act on (see `docs/AGENT_HARNESS_PLAN.md`, weak-model rules).

### 5.6 Apply (one transaction)

`Triage._apply` writes, in one unit of work:
1. the thread's link (`matter_threads`);
2. matter fields (state, due, summary, importance: the highest of its open threads);
3. work changes, each with `matter` set;
4. one `matter_events` row per change, with the message id and the reason;
5. emits `matter.changed {matter, kinds}` for the UI and the brief.

### 5.7 After apply

- **Brief:** if `brief.op != none`, or the matter's state, due or importance changed, update its brief line (section 8).
- **Notifications:** notify on **matter changes**, not emails. "Q4 timesheet: due moved to Fri" instead of "New mail from HR". The existing `notify` rules apply to the matter's change.
- **Cascade offers:** if anything closed, run section 7.

---

## 6. Matter state

```
           ┌──────────────┐ ask arrives  ┌────────────────┐ you reply/act  ┌──────────────────┐
  new ───► │ open         │────────────► │ waiting_on_you │──────────────► │ waiting_on_others│
           └──────────────┘              └────────────────┘ ◄────────────── └──────────────────┘
                 │ fyi only                   │ due/time set        they answer     │ follow_up_on passes
                 ▼                            ▼                                     ▼
              (no brief)                 scheduled ──── time comes ──► waiting_on_you    chase offer
   any state ── done / dropped (with confirmation when work is open; section 7)
```

- **The matter's state is derived first, then judged.** Code derives it from its threads' statuses and open work. If any thread is waiting_on_you, the matter is waiting_on_you. The AI's `matter_state` is a proposal that the validator accepts unless it contradicts open work (for example "done" while a task is open → cascade offer instead).
- **The person's word wins.** Marking a matter done, or reopening it, sets `by = person`, and the AI may not change it for 7 days unless a new email explicitly reopens it ("this is still pending").
- **A reply you send** (`person_replied`) moves the matter to waiting_on_others and offers to close the "reply" work.

---

## 7. Close one, close the rest

### Triggers

- A task marked done, a reminder dismissed or fired-and-done, or a draft sent.
- The person marks a matter done.
- An email says it's done ("approved", "no longer needed"), via the AI's `close` ops.
- You reply in any thread of the matter.

### What happens (code, no model)

1. Gather the matter's **other open items**: tasks, reminders, follow-ups, unsent drafts, the brief line, and other threads still marked waiting_on_you.
2. If there are none, close quietly and log it.
3. Otherwise show **one confirmation**:

```
You replied to Priya about the budget.
Also close these?
  ☑ Task: Send budget numbers (due Fri)
  ☑ Reminder: Fri 10:00 "Budget"
  ☑ Brief: "Priya needs the budget decision by Fri"
  ☐ Thread: "Budget v2 deck" (still waiting on you)
[Close selected]   [Not now]
```

- The defaults are ticked when the item is clearly covered (same action), and unticked when unsure (a different thread with its own ask).
- **"Not now"** keeps everything open and logs it. The offer isn't repeated for the same items.
- **Undo** for 10 seconds after, and from the matter timeline at any time (`matter_events.undo`).
- Where it shows: a toast or sheet where the action happened (thread view, Today, task list), and in chat when Posty did the action.

---

## 8. The live brief

### Model

The brief is a **view of open matters**, stored as `brief_lines` (one per matter), with short morning text on top.

- **Morning run (as today):** the brief agent writes the top line ("the single most important thing today") and re-ranks all lines. It may rewrite any line.
- **During the day:** when a matter changes (5.7), **only its line** is updated:
  - **Template first (no model):** state, due and the latest event fill a line like "**Q4 timesheet** (HR): due Fri, 2nd reminder [mail:402]".
  - **One small model call** only when the matter summary changed meaningfully (`brief.op = update` from triage). The call writes one line from the matter card; it's cheap enough for a weak model.
- **"Since you last looked":** lines with `updated > seen` show at the top with what changed. Opening Today marks them seen.
- **Every line has a `[matter:N]` marker.** Clicking opens the matter page; hovering shows the timeline's latest events.
- **Done matters** drop off the next morning, or show struck through in a "Done today" fold until then.

### Brief agent changes

- New tools: `read_matters(filter)` (open matters with lines and the latest events) and `update_brief_lines([{matter, line, rank}])`.
- `update_brief` stays for the top text.
- `prompts/daily-prep.md` gains "Work from matters: one bullet per matter, never two for the same matter."

---

## 9. Promises you made, and chasing others

Most tools stop at "what do others want from me". The best one also tracks **what you promised** and **what you're waiting for**.

- **Your sent mail is judged too**, for commitments: "I'll send the deck by Thursday". This creates or updates a matter with a `create task` op (you owe it) and `due`.
- **Waiting on others:** when a matter waits and `follow_up_on` passes, Today shows "No reply from Arun in 4 days", with a drafted nudge ready. It's one tap to send after review; nothing sends itself.
- **They answered:** `they_answered` already exists. It moves the matter back to waiting_on_you, or done, and the cascade offer appears if your chase task is still open.

---

## 10. How people see it

### Today: the board of matters

```
Since you last looked (3)
  ● Q4 timesheet · HR · due Fri · 2nd reminder                         [Open] [Done]
  ● Budget decision · Priya · waiting on you · she asked again today    [Reply]
  ● ECO-1104 release · PLM · you were named · fyi                       [Seen]

Needs you (5)            Waiting on others (3)          Coming up (2)
  …                        Arun · deck review · 4 days     Visa appointment · Tue
```

Each **matter card** has:
- the title and who it involves (avatars);
- the state chip;
- the due date;
- the latest change in one line, with time;
- counts ("3 emails · 1 task · 1 reminder");
- one primary action (Reply, Do, Decide, Open) plus Done and Snooze.

### The matter page

- **Header:** title (editable), state, due, people, and actions: Done, Snooze, Merge with…, Split, Rename.
- **Timeline:** every event, newest first. Emails appear inline as collapsed rows that open in place.
- **Work:** open tasks, reminders and drafts, each with its source email.
- **Related matters:** `related` / `part_of` / `follows`, with why.
- **Why it's grouped:** each thread's link reason ("Same sender, subject 91% alike"), with "Not part of this" to unlink.

### Everywhere else

- **Thread view:** a chip at the top, "Part of: Q4 timesheet ▸", with a menu offering Move to another matter or Start a new one.
- **Inbox rows:** a small matter chip when the thread is in an open matter that has other threads ("+2 more").
- **Tasks and Reminders screens:** each row shows its matter, and filtering by matter works.
- **Chat (Posty):** "What's going on with the budget?" answers from the matter: state, timeline and open work, with markers. "Close everything about the timesheet" uses the same cascade sheet.

### People

People pages ("everything open with Priya") come from `matter_people`.

---

## 11. Corrections teach it

- **Move a thread** to another matter, or **unlink** one. This is logged (`how = person`) and stored as a pair (sender stem + subject_core → matter) that adds +3 in the candidate finder (5.3) next time.
- **Merge two matters:** threads, work and events move to the survivor. The other gets `merged_into` and a `same_as` relation. Duplicate open work is offered for closing (section 7).
- **Split a matter:** pick the threads to move, and a new matter starts with them. Work moves with its source thread.
- **Rename** is free and logged.
- **The agent never overrides a person's link.** If a new email seems to belong elsewhere, it adds a `related` relation, not a move.

---

## 12. Prompt and context budget (weak-model harness)

- The AI sees **at most 5 candidate matters**, each at most 6 lines, with open work only. That's about 400 tokens.
- It chooses ids from a list, with no free-form matching.
- Every refusal message names the valid options.
- **One task per run:** link plus work plus state. Drafting stays its own step, as today.
- **Fixed field order and short field names**, matching the contract in 5.4. Examples in the prompt cover the three cases that matter most: a reminder updating a due date, a new ask in an old matter, and a done-signal closing work.
- With the rule engine in front, the AI only sees mail that reaches it, so volume stays small.

---

## 13. Evals and checks

### Fake-model tests (free, run in `make check`)

- **Reminder chain:** ask → reminder → reminder (new threads, same sender, similar subject) gives 1 matter and 1 task with the due date updated, and 0 extra reminders.
- **Id match:** two different senders mention `ECO-1104`; they're linked and the evidence says so.
- **False friend:** same sender, different asks ("Q4 timesheet" vs "Q4 holiday plan") gives 2 matters.
- **Cascade:** reply sent → offer lists the task, the reminder and the brief line; accept → all closed with events; undo → all back.
- **Validator:** an invented id is refused; a duplicate create becomes an update; a past date is dropped.
- **Person wins:** a thread moved by the person is never moved back by the agent.
- **Brief:** a matter change updates exactly one `brief_lines` row; a done matter leaves.

Fixtures: extend `backend/tests/corp_mail.py` with reminder chains, id-linked threads, false friends and promise-in-sent-mail cases.

### Real-mail checks (ask first; they spend the model allowance)

- Run on the person's real mailbox for a fixed window (for example the last 30 days). Report:
  - duplicate task rate, before vs after;
  - link precision (sample 30 links and judge them);
  - matters per 100 important emails;
  - validator refusals per 100 runs.
- Add to `make eval-mail` as a `--matters` mode once Phase 3 lands.

### Metrics in the Cockpit

Open matters, links by `how`, validator refusals, cascade offers accepted vs declined, and brief staleness.

---

## 14. Risks and how we handle them

| Risk | Handling |
|---|---|
| Wrong merges hide an ask inside another matter | Merges are never silent: auto-links need a clear winner with an id match, everything shows "why it's grouped", and unlinking is one tap. A `new` matter that resembles an existing one is flagged as related, never merged. |
| Too many tiny matters | Matters are created only for mail that needs something or has a date. fyi mail stays as threads. |
| Brief churn during the day | Lines update in place; ranking changes only in the morning run or on a state change to waiting_on_you with a due within 48 h. |
| Cost on a weak model | Candidates come from code; the AI call is the existing triage call with ~400 more tokens; brief lines use templates first. |
| Migration of existing tasks | Phase 2 backfills one matter per thread with open work, then merges via the candidate finder with `confidence = medium`, shown for review on Today ("We grouped 12 things. Check them."). |
| Privacy | Everything stays local, as today. Matters are derived data and can be rebuilt. |
| Person-made tasks with no email | They get a matter only when linked; otherwise they stay plain tasks. |

---

## 15. Phases

Each phase ships alone, keeps all tests green, and is checked on real mail (with permission) before the next.

### Phase 1: Stop the duplicates (no new concepts)

- **Build:** `message_marks` (5.1); the candidate finder over **threads** (5.3, scoring threads with open work instead of matters); `task_for` shows open work from the top related threads with evidence; `has_task`/`has_reminder` check related threads too; a reminder email updates the due date of the matching open task (validator rule from 5.5, applied to the old `tasks`/`reminders` lists).
- **Files:** `modules/mail/store.py` (marks), new `modules/mail/related.py` (finder, pure functions), `modules/agent/mail_agent.py` (`task_for`, `Triage._apply`), `modules/planner/module.py` (dedup), `prompts/mail.md` (three lines about related work).
- **Tests:** the reminder-chain, id-match and false-friend tests (section 13), on threads.
- **Done when:** the duplicate task rate on the real mailbox drops (measure before and after).

### Phase 2: Matters exist

- **Build:** the tables from section 4; certain links (5.2); auto-links from the finder; backfill; `matter` on tasks, reminders and the work board; `matter.changed` events; read-only `matter.get` / `matter.list` queries.
- **Files:** new `modules/mail/matters.py` (store, link, events, derive state), contracts in `contracts/mail.py`, migration.
- **Done when:** every open task belongs to a matter, and a reminder chain on real mail lands in one matter.

### Phase 3: The AI decides with closed choices

- **Build:** the prompt blocks A–D (5.4); `record_triage` with `matter` and `work`; the validator (5.5); apply with events (5.6). The old `tasks`/`reminders` fields are accepted for one release and mapped to `create`.
- **Files:** `modules/agent/tools.py` (`_RecordTriage`), `mail_agent.py`, `prompts/mail.md`, new `modules/agent/matter_validator.py`.
- **Done when:** fake-model tests pass, and a real-mail eval (with permission) shows link precision ≥ 90% on a 30-link sample.

### Phase 4: Close one, close the rest

- **Build:** the cascade (section 7) with confirmation, undo and events; a `matter.close` command; a `matter.cascade` query for the UI.
- **UI:** a confirmation sheet from the primitives (`Dialog` / toast), wired into Tasks, Reminders, the thread view, Today and the send flow.
- **Done when:** replying to a thread offers to close its task and reminder, and undo restores them.

### Phase 5: The live brief

- **Build:** `brief_lines`; template lines; one-line model updates; "since you last looked"; brief agent tools and prompt change (section 8).
- **Done when:** an important email updates its brief line within 2 minutes, without a full rewrite.

### Phase 6: People see matters

- **Build:** Today board (section 10); matter card; matter page with timeline, work, people, related and why-grouped; thread chip; move, merge, split and rename (section 11); Posty answers from matters.
- **Done when:** a person can understand their day from Today alone, and fix a wrong grouping in two taps.

### Phase 7: Promises and chasing

- **Build:** judge sent mail for commitments; waiting-on-others with chase drafts (section 9).

---

## 16. Decisions to make

1. **Name in the UI:** Matter / Topic / Item / Loop, or no name, just titles (recommended).
2. **Auto-link threshold:** start strict (id match plus clear winner) and loosen with real data?
3. **Brief during the day:** update lines silently, or also show a small "Updated 11:04" badge on Today?
4. **Sent-mail promises (Phase 7):** on by default, or opt-in?
5. **Keep old triage fields** for one release only, or two?

---

## 17. Research notes (2026-11-21)

- **Gmail AI Inbox** (rolling out to paid Workspace since Oct 2026) replaces the message list with two lists, *Suggested to-dos* and *Topics to catch up on*, above the inbox. This confirms the shift from messages to things. It doesn't describe merging the same to-do across threads. [Google help](https://support.google.com/mail/answer/16845247), [rollout](https://workspaceupdates.googleblog.com/2026/10/gmails-ai-inbox-is-rolling-out-to-paid-Workspace-users.html), [TechCrunch](https://techcrunch.com/2026/01/08/gmail-debuts-a-personalized-ai-inbox-ai-overviews-in-search-and-more).
- **Zep / Graphiti** temporal knowledge graph for agent memory: raw *episodes* become entities and facts with valid-from/valid-to times, and new input is checked against what's known before adding. Matters, events and relations here are the same shape in plain SQLite. [Paper](https://arxiv.org/abs/2501.13956), [Graphiti](https://github.com/getzep/graphiti), [Neo4j write-up](https://neo4j.com/?p=370810).
- **Shortwave / Superhuman:** commitment extraction from threads, and resurfacing threads nobody answered. Neither claims cross-thread task merging. [2026 roundup](https://effectiveaitools.com/posts/best-ai-email-assistants-2026/), [follow-up tools](https://www.neatmail.app/blog/best-ai-tools-email-follow-ups-2026).
- **Takeaway:** nobody we found publicly solves "the same thing arriving as several emails" with a durable record plus confirmation-based closing. That's the edge to build.
