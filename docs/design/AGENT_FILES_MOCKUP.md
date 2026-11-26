# Agent files: mockup

A mockup of one file per agent (`docs/AGENT_OWNERS_PLAN.md` §6b), written out in full for every agent, and how a routine differs from an agent. Nothing is built. Prompt bodies are cut to their first lines; the real ones move over unchanged.

Written 2026-11-25. Open decisions are marked **(open)**.

## Contents

1. [The shape](#the-shape)
2. [Posty](#posty)
3. [Mail agent](#mail-agent)
4. [Brief writer](#brief-writer)
5. [Routines agent](#routines-agent)
6. [First meeting](#first-meeting)
7. [Organizer, if it stays](#organizer-if-it-stays)
8. [An agent the person makes](#an-agent-the-person-makes)
9. [How a file shows on the Agents page](#how-a-file-shows-on-the-agents-page)
10. [Routines: agents or their own thing?](#routines-agents-or-their-own-thing)

## The shape

Every agent is one file, `modules/agent/agents/<id>.agent.md`: identity and limits in the frontmatter, its instructions in the body.

| Field | For | Notes |
|---|---|---|
| `id` | code | Never changes, never shown |
| `name`, `handle` | people | The person can rename; renames live in the database, on top of the file |
| `role` | people | One line on the Agents page |
| `description` | Posty | When to give it work. Posty's hand-over list is built from these |
| `owns` | tools, prompts | Jobs from the owner table (`owners.py`). Its tools come from these, never from a list in the file |
| `tools_off` | tools | Optional: switch off tools it would otherwise have. Can't add any |
| `skills` | know-how | Skills it may load |
| `runs_on` | when it works | `person` (talked to), `mail` (each new email), `routine` (started by a routine), `team` (handed work) |
| `may_assign_to` | team | Agents it may hand work to |
| `talks_to_person` | team | Whether it may answer the person directly |
| `model` | model | Optional: a smaller or larger model for this agent (open) |
| `mascot` | people | Style and seed, as now |

Shared with every agent and never listed: reading and search tools, team tools (`team_inbox`, `team_message`, `team_close`, `team_roster`), `remember`, `list_memory`, `load_skill`, `find_tools`, and later `save_preference`.

---

## Posty

```markdown
---
id: session
name: Posty
handle: posty
default: true
role: Your chief of staff. Does the quick things directly and hands bigger jobs to the team.
description: >
  The lead. Talks with the person everywhere, answers, and does any small job directly:
  moving or marking mail, a draft when asked, a task or reminder, a folder or rule.
owns:
  - talking-and-routing
  - acting-on-mail        # move, mark, archive, block, send with a yes
  - drafts                # when the person asks
  - tasks-and-reminders   # (open) moved from the Organizer
  - folders-and-rules
  - matters               # close, reopen, merge on the person's word
  - panels-and-documents
  - computer              # files and commands, desktop only, always asks
  - skills                # proposes; the person approves
skills: [working-with-the-team, drafting-replies, chasing-follow-ups]
runs_on: [person, team]
may_assign_to: [mail, daily-prep, routines]
talks_to_person: true
mascot: { style: round, seed: posty }
---
This is a working session. Do what the person asks, using tools where they help.
Your scratch folder for this session is {scratch}.

## Where to start
...

## Tasks and reminders            <- the Organizer's few lines, if it folds in (open)
Before adding anything, list what exists with list_tasks or list_reminders...
A thing to do gets a task. A moment to be reminded gets a reminder. Never both...

## Yours, and not yours            <- generated from owners.py, not written by hand
Yours: talking and routing, acting on mail, drafts, tasks and reminders, folders and rules,
matters, panels and documents, files and commands, skills.
Hand over: judging or re-sorting mail -> @mail. The brief -> @brief.
Anything that runs by itself (on a time, an email, a check) -> @routines.
```

## Mail agent

```markdown
---
id: mail
name: Mail agent
handle: mail
role: Reads every new email and decides what matters, what needs a reply and where it goes.
description: >
  Give it work that means judging mail: deciding what matters across many emails,
  re-sorting a folder or a month of mail, or learning from past mail.
  Not for moving or marking one email; Posty does that.
owns:
  - mail-judging          # folder, status, importance, matter, follow-up, deadlines
  - labels                # later, To do 8
tools_off: [draft_reply, draft_forward]   # drafts only inside its judgement
skills: [drafting-replies]
runs_on: [mail, team, person]
may_assign_to: []
talks_to_person: false
reads_untrusted_mail: true     # so nothing that sends, deletes or changes settings, ever
mascot: { style: square, seed: mail }
---
You look after the person's email on {{agent.session.name}}'s team. You work in the
background so they only see what deserves them...

## Yours, and not yours            <- generated
Yours: judging mail, labels. Suggest tasks, reminders and a draft inside record_triage.
Hand over: anything else -> @posty.
```

## Brief writer

```markdown
---
id: daily-prep
name: Brief writer
handle: brief
role: Writes your morning brief from what needs you.
description: >
  Give it anything about the brief on Today: writing it, updating it, or changing how
  it's written.
owns:
  - brief
skills: []
runs_on: [routine, team, person]   # its morning run is the one default routine
may_assign_to: []
talks_to_person: false
mascot: { style: tall, seed: brief }
---
You are {{self.name}}. You own the person's brief at the top of their Today page:
writing it each morning, updating it when asked, and shaping it to how they want it.

## Yours, and not yours            <- generated
Yours: the brief. It links to mail instead of drafting.
Hand over: anything else -> @posty.
```

## Routines agent

New, made in the Routines iteration (To do 1). It **sets up** routines; it doesn't run them (see the last section).

```markdown
---
id: routines
name: Routines
handle: routines
role: Sets up things that run by themselves: on a time, when an email arrives, or when a check fails.
description: >
  Give it anything that should happen by itself later or again: "every Friday, write my
  status", "when an invoice arrives, file it and add a task", "check this endpoint hourly
  and email these people if it's down". Not for a reminder; Posty sets those.
owns:
  - routines              # set up, change, pause, remove, run now
skills: [setting-up-routines]   # starters, conditions, checks, "nothing leaves without a yes"
runs_on: [person, team]
may_assign_to: []
talks_to_person: true     # it asks the questions a routine needs (who to email, how often)
mascot: { style: square, seed: routines }
---
You are {{self.name}}. You set up routines: something starts it, it does some steps,
it tells someone. Nothing runs before the person keeps it...

## Yours, and not yours            <- generated
Yours: routines.
Hand over: a reminder ("remind me…") -> @posty. Judging mail -> @mail.
```

## First meeting

```markdown
---
id: interview
name: First meeting
handle: meeting
role: Gets to know you once, from your past mail.
description: >
  Runs only as its own interview after setup and for follow-up questions on unclear mail.
  Not given other work.
owns:
  - getting-to-know-you
runs_on: [setup]
may_assign_to: []
talks_to_person: true
accepts: []              # takes no messages from the router
mascot: { style: round, seed: meeting }
---
This is {{agent.session.name}}'s first meeting with the person: a short interview so
their mail is looked after the way they would...
```

## Organizer, if it stays

Only if the person decides to keep it **(open)**. Otherwise its job and prompt lines move into Posty, and this file is retired.

```markdown
---
id: organizer
name: Organizer
handle: organizer
role: Keeps your tasks and reminders: adds, changes and clears them, without duplicates.
description: >
  Give it tasks and reminders: adding, changing, completing or removing them,
  including many at once.
owns:
  - tasks-and-reminders
runs_on: [team, person]
may_assign_to: []
talks_to_person: false
mascot: { style: tall, seed: organizer }
---
You are {{self.name}}. You keep the person's tasks and reminders...
```

The trade-off: keeping it costs a hand-over (a second model run) for every "remind me at 5"; folding it in makes Posty's prompt about 20 lines longer and its tool list about 6 tools longer (shown through tool search, so mostly one search away).

## An agent the person makes

Made in chat or pasted in. The same shape, kept in the database, not in the app's folder. A Claude Code, Copilot or Gemini agent file can be pasted: its `name`, `description`, `model`, `skills` and body carry over, `tools` is read as a wish, and anything not used here is shown as such.

```markdown
---
id: a-7f3c               # made by the app
name: Kite tracker
handle: kite
role: Keeps an eye on the Kite launch for you.
description: >
  Give it anything about the Kite launch: what moved, who's waiting, what's at risk.
owns: []                 # jobs without an owner only, chosen on its card (open: which by default)
skills: []
runs_on: [person, routine]
may_assign_to: [posty]   # hands over anything it doesn't own
talks_to_person: true
mascot: { style: round, seed: kite }
---
Follow the Kite launch. Look for mail from the Kite team and anything with "Kite" in it...
```

## How a file shows on the Agents page

Drawn from the same frontmatter. (Text only; the page itself gets a visual mockup before any change.)

```
┌───────────────────────────────────────────────────────────┐
│ (mascot)  Mail agent  @mail                       [On]    │
│ Reads every new email and decides what matters, what      │
│ needs a reply and where it goes.                          │
│                                                           │
│ Its jobs    Judging mail · Labels                         │
│ Works when  A new email arrives · You hand it work        │
│ Can't       Send, delete or change settings               │
│ Skills      Drafting replies                              │
│ Your instructions for its jobs  (2)              Edit     │
└───────────────────────────────────────────────────────────┘
```

---

## Routines: agents or their own thing?

**Recommendation: their own structure.** A routine is not an agent. It's a short record of *what starts it, what it checks, what it does and who it tells*, and when one of its steps needs a model, that step is run by an existing agent.

### Why not an agent

| | Agent | Routine |
|---|---|---|
| What it is | Someone who owns jobs and can talk | A rule: when X, do Y, tell Z |
| How many | A handful | Dozens, made by the person |
| Needs a model | Always | Often not: a reminder, an endpoint check, an email to a list |
| Identity | Name, mascot, roster place | A title, an on/off switch, a run history |
| Tools | From the jobs it owns | None of its own; a model step borrows its agent's |

Today each schedule the person makes becomes its own hidden agent (`scheduled.toml`: "each schedule … becomes its own agent") with **every tool**. That is the gap the owner table closes, and it would get worse with dozens of routines each holding every tool. Linear's Loops work the same way as recommended here: a loop is a trigger and a template, and each run is a conversation with Linear's one agent.

### What a routine looks like

Stored in the database and edited through the Routines agent or the Routines page. The same frontmatter-and-body shape is used to show, export or paste one, so it reads like an agent file without being one.

```markdown
---
id: r-12
title: Weekly status to my manager
on:
  time: { every: week, day: friday, at: "17:00" }
check: null                       # no condition; always runs
do:
  - agent: posty                  # which agent runs the model step, and with its tools only
    task: Write this week's status from my sent mail and open matters.
  - draft_email: { to: [manager], subject: "Weekly status" }
tell:
  - email: { to: [manager], needs_yes: first-time }   # nothing leaves without a yes, once
made_by: routines
on_off: on
---
```

```markdown
---
id: r-13
title: Endpoint watch
on:
  time: { every: hour }
check:                            # no model
  url: https://status.example.com/health
  fails_when: { status_not: 200 }
do: []
tell:
  - email: { to: [oncall@example.com], once_per_failure: true }
---
```

```markdown
---
id: r-14
title: Invoices
on:
  email: { like: "an invoice or a bill" }    # judged by the Mail agent as it reads the email
do:
  - file_to: Finance
  - agent: posty
    task: Add a task to pay it, due on the date in the email.
tell: []
---
```

```markdown
---
id: r-1
title: Morning brief                # the one default routine
on:
  time: { every: weekday, at: "08:30" }
do:
  - agent: daily-prep
    task: Write today's brief.
tell:
  - today_page: brief
made_by: app
---
```

### How the two fit

- **The Routines agent sets routines up; the routines themselves run without it.** Like Posty doesn't run inside every reminder.
- **A model step names an existing agent** (`agent: posty`, `agent: daily-prep`), and runs with that agent's tools and the person's instructions for its jobs. A routine never has tools of its own.
- **A reminder is not a routine.** "Remind me to drink water hourly, 10–20, Mon–Fri" is one reminder with a repeat rule (To do 13), made by Posty, with no model when it fires.
- **The brief becomes the first routine**, with `agent: daily-prep`, instead of a special kind of schedule.

## Open

1. Fold the Organizer into Posty, or keep it (the trade-off is above).
2. Bulk jobs, such as "make tasks from all of this week's mail": who does them. Undecided; not needed for the first step.
3. What an agent the person makes gets by default.
4. Whether `model` per agent is wanted at all, or every agent uses the one model the person picked.
5. Routines as their own structure, with model steps run by an existing agent (recommended above).

---

## The whole prompt, with personal context

Added 2026-11-25. The artifact's "Whole prompt" tab shows it assembled for three runs (Posty in chat, the Mail agent judging, the Brief writer's morning run); "Context today" maps every source.

**Today, 18 sources** reach an agent: the system prompt, the card's who-you-are block, the agent prompt, extra text appended to it, a person-made agent's instructions, About the person, five personalized prompt files, approved preferences, brief wishes, corrections, mailbox signals, memory files, facts from mail, other tools, Your day or the brief, This run, and the conversation. Personal context sits in seven of them, ranked differently.

**Proposed: 12 sections in four groups**, in this order (stable first, so the model server can cache them):

| # | Section | Group | From | Who sees it |
|---|---|---|---|---|
| 1 | Rules | Stable | `system.md`, with the new order of what wins | everyone |
| 2 | Who you are | Stable | the agent file's frontmatter, `owners.py`, the other agents' descriptions | everyone |
| 3 | Your job | Stable | the agent file's body | everyone |
| 4 | Your other tools | Stable | tool names not loaded yet | agents with tool search |
| 5 | Your instructions | Personal | `preferences`, keyed by job; everyone's rows plus the agent's own jobs' | everyone |
| 6 | About the person | Personal | Profile | everyone |
| 7 | What they corrected | Personal | mail corrections, brief reactions, who they write to | only the agent whose job it is |
| 8 | What's known | Personal | memory and facts from mail, in three tiers: confirmed by them, noted by agents, guesses from mail; each with its source; picked by relevance within 8,000 characters | everyone |
| 9 | Now on screen | Live | Your day (Posty), the brief now (Brief writer) | that agent |
| 10 | This run | Live | why it started, open team tasks, the time | everyone |
| 11–12 | Conversation | Conversation | summary plus last messages; tool results and mail wrapped as untrusted | everyone |

**What wins when they disagree** (`system.md`): 1 Rules and tool limits, and a job that isn't yours goes to its owner; 2 Your instructions; 3 About the person; 4 What they corrected; 5 Your job; 6 What's known, facts never orders.

**Where the personal sources go:** the per-agent extra text, the importance/senders/categories/topics files, brief wishes and approved preferences all become rows in Your instructions; about-me joins About the person; memory files and facts from mail merge into What's known; corrections, brief reactions and mailbox signals become What they corrected.
