# Agents and categories

How many agents NexusAI has, what starts each one, and how mail gets its folder. Last reviewed: 2026-11-04.

Settings named like `agent.learn_emails` are in `backend/src/nexusai/kernel/defaults.toml`.

## Agents

There are **5 agents**, plus 3 helpers that make a single model call. All of them are one engine with different instructions and tools, and every model call goes through the gateway (`modules/agent/gateway.py`). The Agents list on the Agent channel page shows what runs and when it runs next.

| Agent | What it does | Prompt | Tools |
|---|---|---|---|
| **Chat** | Talks to the person, and does what they ask | `session.md` | All, with risky ones asking first |
| **Mail agent** | Judges mail, learns about the person, and suggests where mail should go | `mail.md` | A small set for mail (`MAIL_AGENT_TOOLS`) |
| **First meeting** | Asks a few questions, so mail is judged the way the person would | `interview.md` | All. Changes ask first, because it read mail |
| **Your brief** | Writes the brief at the top of Today | `daily-prep.md` | All |
| **Scheduled** | Runs a prompt the person set up, on a schedule or an event | `scheduled.md` | All |

| Helper | What it does | Started by |
|---|---|---|
| Summary | Summarizes a conversation | Summarize on a thread |
| Draft reply | Writes a reply for the person to check. Nothing is saved or sent | Draft reply on a thread or on Today |
| Compact | Shortens a long chat for the model | Compact, or a chat getting too long |

The Agents list also shows **Reading past mail** and **Inbox review** as their own rows. Both are runs of the Mail agent, in its one chat.

## What starts each one

A typed message, an event and the clock all start a run the same way. One thread hands out waiting work (`modules/agent/triggers.py`), and a finished run wakes it.

| Run | Agent | What starts it | When |
|---|---|---|---|
| A typed message, or Ask agent | Chat | The person | Whenever they ask |
| Judging new mail | Mail agent | `mail.needsTriage` | Each conversation with new mail that the rules didn't send to its folder |
| Reading past mail | Mail agent | `mail.changed`, `mail.historyFinished` | Once, when `agent.learn_emails` (400) unjudged emails are here, or no more is coming. Read more can repeat it |
| Tidying its notes | Mail agent | The last past email being read | Once, after that reading |
| After the person sends | Mail agent | `mail.sent` | Works out what comes next. Their plate updates first, with no model |
| After a question is answered | Mail agent | The person's answer | Judges that conversation again with the answer |
| Hourly check | Mail agent | The `mail-hourly` schedule | Each hour with mail handled since the last check, and no run if there's nothing new. Off until the Mail agent settings are saved with Hourly or Both |
| Inbox review | Mail agent | The `mail-review` schedule | Mondays at 09:00, and after reading past mail |
| Getting to know the person | First meeting | Reading past mail finishing | Once |
| Your brief | Your brief | The `mail-brief` schedule | Every day at 08:30 |
| Prompt schedule | Scheduled | A schedule the person made | When they set |
| Event trigger | Scheduled | `mail.received` or `mail.urgent` | Each time, if the person set one up |

Mail agent runs happen one at a time, because they share one chat. New mail goes ahead of background work. Your brief is independent of optional past-mail reading; First meeting still starts automatically after that reading, or can be started manually. `agent.max_running_sessions` (3) limits how many chats run at once.

### Without a model

These cost no tokens: fixed rules, mail categories by header, reminders and follow-up notices (the time check in `modules/agent/scheduler.py`), mail sync, and search indexing.

### When the model can't be used

Every model call goes through one pacer, across all agents.

| What happens | What the app does |
|---|---|
| A limit is set | `NEXUSAI_MODEL_CALLS_PER_MINUTE` keeps calls within it, and a call waits for a free slot. Off by default |
| The server answers 429 | It waits as long as the server says, or `agent.rate_limit_wait_seconds` (10), doubling each time, for up to `agent.rate_limit_retries` (3) retries |
| The wait is over `agent.rate_limit_longest_wait` (60 seconds), or retries run out | Automatic runs go back in line and try again later, so no mail is lost. A person in a chat sees the error |
| No model, or today's token limit is used up | Automatic runs wait, and carry on when the model is back. Mail keeps syncing |

## Categories

A conversation has one main category, and can have more added by hand. Each category shows in the sidebar like a folder.

### Where a category comes from

| Source | Example | Created by |
|---|---|---|
| Starter categories | PLM, Swarm, 3GPP Briefing | `mail.starter_categories`, once for each Home |
| Mail headers | Promotions, Updates, Forums, Social | `_builtin` in `modules/mail/rules.py`, with no model |
| The person | Anything | The sidebar, Settings or chat |
| The Mail agent | Job search, Finance | Filing mail, up to 12 of its own |
| Suggestions | HR, or filing all mail from some senders | The agent suggests, and the person decides on Today |

### How mail gets its category

```text
new mail
  → the person's rules and starter rules, first match wins
  → mail headers (Promotions, Updates, Forums, Social)
  → Mail agent, unless a rule said to skip it
```

| Who set it | Can change it later |
|---|---|
| The person | Only the person |
| A rule the person or the app set | The person. The agent keeps it |
| A guess from mail headers | The person or the agent |
| The agent | The person, the agent or a rule |

### Starter categories

| Mail | What happens |
|---|---|
| Automated, such as `[PLM] Build 12 passed` | Goes to its folder with no model call, and stays out of Priority |
| A reply, such as `Re: [PLM] Build 12` | Stays in the folder, and the agent reads it. If it's important, it also shows in Priority |
| Automated, with a subject that could matter, such as `escalated` or `action required` | Stays in the folder, and the agent reads it |

These folders are never suggested for Priority, though the person can add one. Mail already here is filed when the starter is added.

### Keeping duplicates out

No mail is read twice for any of this.

1. **Overlapping names become one.** HR, HR feedback and HR communication share the word HR (`modules/agent/category_names.py`). Words that only describe the kind of mail don't count, so Product updates doesn't join Updates. The shortest name is kept.
2. **The agent is told what exists.** Each email it judges comes with the existing and suggested categories.
3. **A suggestion needs evidence.** Each conversation that would go in it is recorded, and the card appears at `agent.category_suggestion_min_threads` (5). Accepting files all of them, with no model call.
4. **A no is remembered.** That name and anything overlapping it isn't suggested again.
5. **Different words for the same thing,** like HR and People team, are folded by the Inbox review, which sees only the names and can only fold suggestions.
6. **A one-time tidy** runs at startup for what was named before this. Overlapping suggestions become one, and folders the agent made merge into the shortest name, keeping their mail. Folders the person made aren't touched.

### Empty folders

A category or folder with no mail is hidden from the sidebar, unless it's the one open. It isn't deleted, and comes back when mail arrives. Settings lists them all, and only an explicit delete removes one.

### Priority inbox

A conversation in the Inbox shows in Priority if any of these is true:

- The agent marked it important.
- It's waiting on the person.
- Its category is in Priority.
- It's from the last 7 days, not low importance, with no category yet, so new mail isn't hidden before it's judged.

A category joins Priority in one of three ways:

| Way | How |
|---|---|
| By hand | Right-click it in the sidebar, or use Settings |
| Chat | "Put Customers in my priority inbox" |
| Suggestion | The Inbox review sees how much of each category needed the person, and suggests up to three. A card on Today shows the app's own counts, and a no is remembered |

Promotions, Updates, Forums and Social are never suggested. Server folders can't join Priority yet.


## Coordination and feedback

Assignments on Agent channel include an owner, purpose, expected output, evidence and reported state. Missing outcomes are blocked for review; a chat finishing does not mean the assignment succeeded. The message cap resets each run. Cockpit shows the durable work queue and failure controls.

All writers use the shared profile/context service. Preferences are approved, scoped instructions with expiry and version restore under Prompts and memory. Mail-review runs can propose a higher-level instruction from real feedback observations, but cannot approve it. Chat ratings and opens are recorded as evidence, not automatic policy changes. Read flags describe mailbox state, and silence is not inferred disapproval.

Schedules carry an explicit IANA timezone. Pausing prevents pending automatic runs; Run now is an explicit one-off request. Digest catch-up is bounded and advances its ID cursor only after success. Overdue notifications do not mark work complete. For detailed invariants and validation limits, see [implementation](EMAIL_AGENT_IMPLEMENTATION.md).
