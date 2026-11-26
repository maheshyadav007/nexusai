# Who does what: one owner for each job

> **Since 2026-11-26:** the file shape in §6b is replaced by `docs/PLUGIN_FORMAT_PLAN.md` (Anthropic's field names; `owns` becomes jobs listed in `tools`). The owner rule, clusters and steps here still apply.

> **The idea.** Posty does every small job that needs few instructions, directly, with no hand-over. A specialist agent exists only where a job needs a lot of its own instructions, runs without the person, or reads untrusted mail at scale. A single table in code says who owns each job; tools, prompts, Posty's hand-over list and the roster are read from it. Preferences (`docs/PREFERENCES_PLAN.md`) are keyed by the same jobs.

Status: plan, 2026-11-25, reorganised the same day on the person's direction ("small tasks that don't need much instruction go to Posty; those that need special instructions go to other agents"). To do item 10. Nothing built. Written with personalization (To do item 7) in mind.

---

## 1. Why

- "Set an hourly reminder…" bounced between reminders and schedules, and asking who owns what showed the split had grown one tool at a time: some jobs have two makers, some none, and one agent can reach a job two ways. A weak model given two paths takes the wrong one some of the time.
- Every hand-over costs a second model run and a chance to lose detail. For a one-line job ("remind me at 5", "move this to Finance") that's pure cost.
- Personalization needs to know where an instruction goes. Without one owner per job there's no right answer.

## 2. Today

Tool sets live in `backend/src/nexusai/modules/agent/tools.py`; cards in `modules/agent/agents/*.toml`; prompts in `modules/agent/prompts/`.

| Agent (id) | Prompt | Tools today |
|---|---|---|
| Posty (`session`) | `session.md`, 77 lines | Every tool except `ORGANIZER_ONLY`, `MAIL_AGENT_ONLY`, `BRIEF_AGENT_ONLY` |
| Mail agent (`mail`) | `mail.md`, 100 lines with examples | Judging: `TRIAGE_TOOLS`. Chat or team task: `MAIL_AGENT_TOOLS` |
| Brief writer (`daily-prep`) | `daily-prep.md`, 41 lines | `BRIEF_TOOLS` |
| Organizer (`organizer`) | `organizer.md`, 23 lines | `ORGANIZER_TOOLS`: tasks and reminders |
| First meeting (`interview`) | `interview.md`, 37 lines | `INTERVIEW_TOOLS` |
| Scheduled prompts (`scheduled`) | the person's prompt | Every tool, including the Organizer's |
| Agents the person makes | their card | Every tool, including the Organizer's |

What goes wrong:

| Job | Problem |
|---|---|
| Tasks and reminders | The Organizer's job, but it needs only 23 lines of instructions, so every "remind me at 5" costs Posty a hand-over and a second run. `propose_task` and `propose_reminder` are withheld from Posty as the Organizer's, yet the Organizer doesn't have them; the Mail agent has them **and** `record_triage`'s `tasks` and `reminders`. Scheduled prompts and person-made agents can delete them directly. |
| Drafts | Posty, the Mail agent in chat and the Brief writer all have `draft_reply`. Drafting already has its own instructions inside the tool (`draft-reply` prompt, `mail_agent.py`), so who calls it matters little. |
| Routines | Posty's only through "every tool", never written down; they overlap with reminders (To do 13). |
| Folders, rules, matters | Posty's through "every tool", never written down. |
| Preferences | Three tools: `propose_preference`, `save_personal_prompt`, `remember` (item 7 fixes this). |
| Hand-overs | `session.md` lists them by hand (lines 52–58); `owners_of_withheld` knows only the Organizer. |

## 3. The rule for who does what

A job goes to **Posty** unless one of these is true. Then it goes to a **specialist**:

1. **It needs a lot of its own instructions:** a long prompt, examples or a fixed format that would bloat Posty's prompt for every other job (judging mail, the brief, setting up routines).
2. **It runs without the person:** on new mail, on a clock or on an event, so nobody is there to ask (judging mail, the brief, running routines).
3. **It reads untrusted mail at scale:** then it must not have tools that send, delete or change settings (the Mail agent, Rule of Two in `docs/AGENT_HARNESS_PLAN.md`).

Two lighter ways to give Posty special know-how without a new agent:
- **Instructions inside the tool**, as drafting does today: `draft_reply` runs its own short drafting prompt, so Posty needn't carry it.
- **A skill** loaded only when needed (`load_skill`), such as `meeting-prep`.

## 4. The clusters

### Posty: everything small, done directly

| Cluster | Jobs | Tools |
|---|---|---|
| **Talk and find** | Answer, search, read mail and documents, explain, route | reading and search tools, `ask_user`, `team_assign` |
| **Act on mail** | Move, mark, archive, block a sender, draft a reply or forward when asked, send with the person's yes | `update_mail`, `move_sender`, `draft_reply`, `draft_forward`, `save_draft`, `delete_drafts`, `send_mail` |
| **Tasks and reminders** (from the Organizer) | Add, change, complete, remove; one-off and simple repeats; from what the person says or from an email they're looking at | `create_/update_/delete_tasks`, `create_/update_/delete_reminders` |
| **Organize** | Folders, rules, panels, documents, matters (close, reopen, merge on the person's word) | category, rule, panel, document and matter tools |
| **Personal** | Save what the person wants (item 7), propose a skill | `save_preference`, `propose_skill` |
| **Computer** | Files and commands, desktop only, always asking first | file tools, `run_command` |

### Specialists: jobs that need their own instructions

| Agent | Cluster | Why it's a specialist | Tools |
|---|---|---|---|
| **Mail agent** (`mail`) | **Judge mail**: folder, status, importance, matter, follow-up, deadlines; suggest tasks, reminders and a draft inside the judgement; learn from past mail; re-sort many emails; labels later (To do 8) | All three: a 100-line prompt with examples, runs on every new email, reads untrusted mail | `record_triage`, `save_what_i_learned`, reading tools, `suggest`, `notify_person`; `update_mail` only on a team task. Nothing that sends or deletes |
| **Brief writer** (`daily-prep`) | **The brief**: what needs the person today, in its format, with citations, learning from reactions | 1 and 2: its own format and feedback rules, runs on its own each morning | `read_plate`, `update_brief`, reading tools |
| **Routines agent** (new, made in the Routines iteration, To do 1) | **Set up routines**: on a time, on an email, on a check; conditions, recipients, what to do; pause and remove | 1: conditions, checks and "nothing leaves without a yes" need their own instructions. Running a routine is then the routine itself, with no person there (2) | `create_schedule`, `update_schedule`, `remove_schedules`, `run_schedule`, and the routine tools from item 1 |
| **First meeting** (`interview`) | **Get to know the person** once, from their past mail | 1: a scripted conversation | as today, with `save_preference` replacing `save_personal_prompt` |

### Shared by every agent: remembering facts

Any agent can come across something new while doing its own job: a new manager in a thread the Mail agent judges, a project name in the brief, a person's role while Posty drafts. So **every agent can save a fact with `remember`**, built-in, Routines, scheduled prompts and the person's own agents alike, not only Posty. This is how it works today (every tool set has `remember`), and the plan keeps it on purpose, as a shared job rather than an owned one.

Kept safe the same way as now:
- **Facts, not orders.** Memory is background; it never becomes an instruction (`system.md` rule 6). A wish ("keep the brief short") goes to `save_preference` instead, which is what separates memory from personalization (item 7).
- **From mail, only what's lasting**, one short line each, as `mail.md` already says, and the Mail agent records it through `record_triage`'s `learned` while judging. Text in mail asking to be remembered is never followed.
- **A cap per run** (`MOST_REMEMBERS_PER_RUN`, 3 today) and the person can see and remove every note, with who saved it and from where.
- **Before saving, check it isn't there** (`list_memory`), so five agents don't write the same fact five times. A small test covers two agents meeting the same fact.

**The Organizer is folded into Posty.** Its whole prompt is 23 lines: "list before adding, use local time, a task or a reminder, never both, link to the email". Those lines move into Posty's prompt (or a short skill), and its tools become Posty's. Repeating reminders (To do 13) stay a reminder job, so Posty's; "when X happens, do Y" and "every hour, check Z" go to the Routines agent. That's the line the drink-water request needed.

**Scheduled prompts and agents the person makes** get the reading and team tools only, plus whatever their card adds. They never get a specialist's tools; they hand over like everyone else.

## 5. The roster

| Agent | Handle | One line on the Agents page |
|---|---|---|
| Posty | @posty | Your chief of staff. Does the quick things directly: mail, tasks, reminders, folders, drafts. Hands bigger jobs to the team |
| Mail agent | @mail | Reads every new email and decides what matters, what needs a reply and where it goes |
| Brief writer | @brief | Writes your morning brief from what needs you |
| Routines agent | @routines | Sets up things that run by themselves: on a time, when an email arrives, or when a check fails (from the Routines iteration) |
| First meeting | @meeting | Gets to know you once, from your past mail |

## 6. How it's built

### One table in code

A new module, `modules/agent/owners.py`: each job, its owner, and the tools only the owner has. The cluster names above are the job names.

- `allowed_for(agent, origin, has_email)` becomes: the owner's jobs' tools, plus a shared set (reading, team tools, `remember`, `list_memory`, `load_skill`, `find_tools`, later `save_preference`), plus today's per-origin extras (`ask_user` when typing, `update_mail` on a team task, `save_what_i_learned` on the learning run, `TRIAGE_TOOLS` when judging).
- `withheld_for(agent)` becomes: every tool another agent owns. It applies to Posty, scheduled prompts and person-made agents alike.
- `owners_of_withheld` reads the table, so calling another agent's tool always answers "That's @mail's job. Hand it over with team_assign."
- `MAIL_AGENT_ONLY`, `BRIEF_AGENT_ONLY` and `ORGANIZER_ONLY` go away.
- Cards gain `owns = [...]`, checked against the table at start-up, so the Agents page and `team_roster` show each agent's jobs.

### Keep Posty light on a weak model

Posty gains the task and reminder tools, so its tool list grows. Tool search already keeps that cheap: `LEAD_SHOWN` decides what's shown up front, and `find_tools` brings the rest. `list_tasks` and `list_reminders` are already shown; `create_tasks` and `create_reminders` join them, the rest stay one search away. Posty's prompt gains the Organizer's few lines, under "Tasks and reminders".

### Prompts from the same table

- Each prompt gets a short generated section, **"Yours, and not yours"**: its jobs, and who to hand everything else to.
- Posty's hand-over list in `session.md` is generated from the table.
- The Organizer's card and prompt are retired. Its chats and stored references (`organizer` in `module.py` and `tools.py`) point to Posty; tasks it made keep their history.

## 6b. One file per agent

Researched 2026-11-25. The frontier tools have settled on **one Markdown file per agent: YAML frontmatter for identity and limits, the body as its instructions**:

| Tool | File | Required | Other fields |
|---|---|---|---|
| Claude Code | `.claude/agents/<name>.md` | `name`, `description` | `tools`, `disallowedTools`, `model`, `effort`, `skills`, `memory`, `mcpServers`, `hooks`, `permissionMode`, `maxTurns`, `color` |
| VS Code / Copilot | `.github/agents/<name>.agent.md` | `description` | `name`, `tools`, `agents` (who it may call), `handoffs`, `model`, `skills`, `user-invocable`, `disable-model-invocation`, `mcp-servers` |
| Gemini CLI | `.gemini/agents/<name>.md` | `name`, `description` | `tools`, `mcpServers`, `model`, `temperature`, `max_turns`, `timeout_mins`, `kind: remote` (an A2A agent) |
| Codex | `.codex/agents/<name>.toml` (the exception: TOML) | `name`, `description`, `developer_instructions` | `model`, reasoning effort, feature switches |
| A2A (agents across apps) | `agent-card.json`, served by the agent | name, description, skills, how to reach it | signatures |

What they agree on:
- **`description` is the router's input:** it says *when* to give this agent work, written for the lead model, not for people.
- **The body is the prompt**, so identity and instructions are read and changed together.
- **Tools are a list in the file**, narrowed from "everything" (`tools`, `disallowedTools`); skills and MCP servers are attached by name.
- **Only Claude Code has a colour; nobody has an avatar.** NexusAI's mascots and handles are ours.

Today NexusAI splits each built-in agent across two files: a card, `modules/agent/agents/<id>.toml` (id, name, handle, role, `can_do`, `may_assign_to`, `accepts`, mascot), and a prompt, `modules/agent/prompts/<id>.md`. Person-made agents are cards in the database with `instructions`.

**Recommended:** one `modules/agent/agents/<id>.agent.md` per agent, in the shape everyone uses, with our fields added:

```markdown
---
id: mail                    # never changes, never shown
name: Mail agent            # shown; the person can rename it (kept in the database, on top)
handle: mail
description: >              # for Posty's routing, as in every other tool
  Give it work that means judging mail: deciding what matters, re-sorting many emails,
  or learning from past mail. Not for one quick move or mark; Posty does those.
role: Reads every new email and decides what matters, what needs a reply and where it goes.
owns: [mail-judging, labels]    # jobs from owners.py; its tools come from these
skills: [drafting-replies]
may_assign_to: []
accepts: [person, assign, ask, note]
talks_to_person: false
mascot: { style: square, seed: mail }
---
You are {{self.name}}. ...the prompt, as mail.md is now...
```

- **`owns` replaces a tool list.** Tools come from the owner table (§6), so a file can't hand itself a job another agent owns. A `tools_off` list may narrow further, never widen.
- **`description` (for routing) is new** and separate from `role` (for people). Posty's hand-over list is built from the descriptions.
- **The person's renames, and later their instructions, stay in the database on top**, so the shipped file never changes under them.
- **Agents the person makes use the same shape**, so one can be pasted or imported from a Claude Code, Copilot or Gemini file: `name`, `description`, `model`, `skills` and the body carry over; `tools` is read as a wish and limited to what our table allows; unknown fields are ignored and shown as "not used here", as plugins do (`docs/PLUGINS_PLAN.md`).
- **An A2A card can be generated from the file later**, if NexusAI agents are ever reached from outside.

Every agent's file is written out in `docs/design/AGENT_FILES_MOCKUP.md`, with how routines differ from agents.

This is step 4 below, done together with "prompts from the table", since both rewrite the same files.

## 7. With personalization in mind (item 7)

1. **Preferences are keyed by job, not by agent.** `for` takes a job from the table (`everyone`, `mail-judging`, `drafts`, `tasks-and-reminders`, `brief`, `routines`, …), and whoever does the job reads them. Folding the Organizer into Posty, or adding the Routines agent later, moves nothing in the person's preferences.
2. **The list of `for` values comes from the table**, so a new job appears in `save_preference` and in Settings › Your agents by itself.
3. **Each agent's "Your instructions"** holds everyone's rows plus the rows for the jobs it owns. Posty, owning most small jobs, reads most rows; the specialists read only theirs, which keeps their prompts short.
4. **Memory is not personalization.** Every agent may `remember` facts (§4); only `save_preference` stores what the person wants done. An agent that hears a wish saves a preference, not a memory note.
5. **Ownership is a limit, not a preference.** Your instructions change *how* a job is done, never *who* does it. Moving a job is a setting on the card.
6. **`save_preference` is shared:** Posty in chat, the Brief writer reading brief comments, the first meeting, and the Mail agent for suggestions it infers from corrections.

## 8. Steps

Each step is small, shippable and tested with a fake model. No real-model eval without asking.

1. **The table, same behaviour.** `owners.py` and the cards' `owns`, reproducing today's sets exactly. A test compares old and new sets; a walking test checks every tool is shared, owned once, or per-origin.
2. **Fold the Organizer into Posty.** Move its tools and its few prompt lines; retire its card; point its references to Posty. Tests: "remind me at 5" is made by Posty in one run, with no hand-over; a duplicate is still caught.
3. **Close the other gaps, keep memory shared.** The Mail agent loses `propose_task`, `propose_reminder`, and drafting in chat (it suggests inside `record_triage`); the Brief writer loses `draft_reply`; scheduled prompts and person-made agents lose specialists' tools but keep `remember`. Tests for each, and one that every agent's tool set has `remember`.
4. **One file per agent, prompts and roster from the table.** Merge each card and prompt into `<id>.agent.md` (§6b), add `description` for routing; "Yours, and not yours", Posty's generated hand-overs, the roster's jobs and the Agents page lines above.
5. **Shown who made it.** Tasks, reminders and drafts say who made or suggested them. A screen change, so a mockup first.
6. **Try it on the real account** (ask first): a reminder, a task from an email and a draft are done by Posty in one run; "re-sort last month's mail" goes to the Mail agent.

Personalization (item 7) starts after step 4. The Routines agent joins in the Routines iteration (item 1), with repeating reminders (item 13).

## 9. Open questions

1. **Fold the Organizer into Posty** rather than keep it. (Recommended, by the rule in §3.)
2. **Drafts:** Posty when asked, the Mail agent only inside its judgement. (Recommended; the drafting instructions travel with the tool.)
3. **Bulk work** like "make tasks from all of this week's mail": Posty, or the Mail agent, which already reads mail at scale? (Leaning: the Mail agent suggests, Posty keeps what the person chooses.)
4. **Person-made agents:** reading and team tools by default, more only from the card. (Recommended.)
5. **Preferences keyed by job** (§7.1). (Recommended.)

## 10. Done when

- One table in `owners.py` decides every agent's tools, what's kept from it, its "Yours, and not yours" section, Posty's hand-overs and the roster.
- Small jobs (a reminder, a task, moving mail, a draft) are done by Posty in one run; jobs needing special instructions go to their specialist in one hand-over.
- No job has two makers or two paths in one agent; the walking test passes.
- Checked on the real account.
