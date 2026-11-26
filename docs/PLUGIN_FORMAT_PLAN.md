# One format: everything is a plugin

> **The idea.** Agents, skills, connectors and routines are files in Anthropic's Claude Code plugin format, with Anthropic's file names and field names. The only difference between ours and anyone else's is where they come from: some plugins ship inside the app, the company can push some, the person installs some, and what the person makes lives in a plugin of their own. One loader reads them all, in one order of what wins.

Status: plan, 2026-11-26. Nothing built. Supersedes the file shape in `docs/AGENT_OWNERS_PLAN.md` §6b, "The shape" in `docs/design/AGENT_FILES_MOCKUP.md`, and the format half of `docs/PLUGINS_PLAN.md` (its research, review card, secrets and headers still apply). Names checked against the Claude Code docs on 2026-11-26 (sub-agents, skills, mcp, plugins-reference, marketplace-reference, hooks, routines, memory).

## Contents

1. [Why one format](#1-why-one-format)
2. [The rule for names](#2-the-rule-for-names)
3. [What NexusAI has, in Anthropic's names](#3-what-nexusai-has-in-anthropics-names)
4. [The layout](#4-the-layout)
5. [An agent file](#5-an-agent-file)
6. [Skills, connectors, routines](#6-skills-connectors-routines)
7. [Where plugins come from, and what wins](#7-where-plugins-come-from-and-what-wins)
8. [Jobs, tools and ownership](#8-jobs-tools-and-ownership)
9. [Instructions and memory are not plugins](#9-instructions-and-memory-are-not-plugins)
10. [Trust](#10-trust)
11. [Keeping a weak model's prompt small](#11-keeping-a-weak-models-prompt-small)
12. [What changes in the code](#12-what-changes-in-the-code)
12b. [Seeing what's happening](#12b-seeing-whats-happening)
13. [Steps](#13-steps)
14. [Decided here](#14-decided-here)

---

## 1. Why one format

- Today there are four shapes: agent cards (`agents/*.toml`) plus prompts (`prompts/*.md`), skills (`SKILL.md`), connectors (rows from the Connectors page) and schedules (rows, each turned into a hidden agent with every tool). The person's agents are a fifth, cards in the database. Each has its own loader, its own trust rule and its own page.
- The plans in flight (one owner per job, preferences, routines, plugins) each touch these shapes. Changing them one plan at a time means rebuilding the loader four times.
- Claude Code, Codex and Copilot have settled on one plugin layout. Using it as is means a Claude Code agent or skill installs here unchanged, ours can be read there, and there's nothing of our own to design or document.

## 2. The rule for names

1. **Where Anthropic has a name, use it, with Anthropic's meaning.** File names, folder names, field names and values: `agents/`, `skills/<name>/SKILL.md`, `.mcp.json`, `.claude-plugin/plugin.json`, `name`, `description`, `tools`, `disallowedTools`, `model`, `effort`, `maxTurns`, `skills`, `mcpServers`, `userConfig`, `sensitive`. No synonyms (`tools_off`, `owns`, `runs_on`, cards, audiences go).
2. **What only NexusAI has goes in one place, named `nexusai`:** a `nexusai:` map in frontmatter or JSON, and a `nexusai/` folder in a plugin for whole files Anthropic has no place for. Claude Code ignores unknown fields and folders, so our files still load there. This is the vendor-folder rule from Agent Plugins 1.0.
3. **Anthropic's words on screen too**, where they're plain English: Agents, Skills, Connectors, Plugins, Routines, Instructions, Memory, Marketplace. "Card", "audience" and "scheduled prompt" leave the screens.

## 3. What NexusAI has, in Anthropic's names

| NexusAI today | Anthropic's name | Where it lives in a plugin |
|---|---|---|
| Agent card (`agents/*.toml`) and its prompt (`prompts/*.md`) | **Subagent** file | `agents/<name>.md` |
| Person-made agent (database card) | Subagent file, user scope | `agents/<name>.md` in the person's own plugin |
| Skill | **Skill** | `skills/<name>/SKILL.md` |
| Connector (MCP server) | **MCP server**; "connector" on claude.ai | `.mcp.json` |
| Schedule, event trigger, the brief's morning run, judging each new email | **Routine**: "a prompt, … and a set of connectors, packaged once and run automatically", with triggers | `nexusai/routines/<name>.md` (Anthropic keeps routines outside plugins; we ship some, so they go in our folder) |
| Posty leading the team, team tasks, the agent channel | **Agent team**: lead, teammates, shared task list, mailbox | Code, not files (`team.py`, `channel.py`) |
| Preferences, personal prompt files, per-agent extra text | **Instructions** (`CLAUDE.md`) and **rules** (`.claude/rules/*.md` with `paths`) | Not in plugins; see §9 |
| Memory notes | **Auto memory**, types `user`, `feedback`, `project`, `reference` | Not in plugins; see §9 |
| Tool approvals (`policy.py`, `guard.py`) | **Permissions**: `deny`, then `ask`, then `allow` | Code; the company layer can add rules (§7) |
| Hooks | **Hooks** | Read, shown as "not used here" (§10) |

## 4. The layout

Every plugin, ours and anyone's:

```
<plugin>/
  .claude-plugin/plugin.json     # or plugin.json at the root, or .codex-plugin/plugin.json
  agents/<name>.md
  skills/<name>/SKILL.md         # plus its own files, read when needed
  .mcp.json                      # remote MCP servers
  nexusai/routines/<name>.md     # only NexusAI reads this
```

`plugin.json` uses Anthropic's fields as they are: `name` (kebab-case, required), `displayName`, `version`, `description`, `author`, `homepage`, `repository`, `license`, `keywords`, `defaultEnabled`, `userConfig`, `dependencies`, and `skills` / `agents` / `mcpServers` paths. Ours add `nexusai: { minApp: "…" }` only if needed.

**The plugins that ship with the app**, one per area, so an area can be switched off as a whole and each folder stays small:

| Plugin | Agents | Skills | Routines |
|---|---|---|---|
| `nexusai` | `session` (Posty), `interview` (First meeting) | `working-with-the-team`, `tasks-and-reminders` (the Organizer's few lines), `nexusai-guide` (To do 14) | — |
| `mail` | `mail` (Mail agent) | `drafting-replies`, `chasing-follow-ups` | `on-new-mail`, `on-sent-mail` |
| `brief` | `daily-prep` (Brief writer) | — | `every-weekday-morning` |
| `routines` | `routines` (Routines agent) | `setting-up-routines` | — |
| `meetings` | — | `meeting-prep` | later: meeting prep from mail (To do 12) |

They live in the app at `backend/src/nexusai/plugins/<plugin>/`, read-only, and are updated with the app. `nexusai` and `mail` can't be switched off; the rest can.

Prompts that belong to one tool (`draft-reply.md`, `summary.md`, `compress.md`, `mail-digest.md`, `starter-*.md`) are not agents or skills. They stay with their tool's code. `system.md` stays in code too: it's the rules, not an extension.

**The Mail agent's run prompts** (`prompts/triggers/`, 18 files with their `-model` variants) move into the `mail` plugin. Those an event starts become routine bodies: `mail-one` and `mail-many` for On new mail, `mail-sent` for On sent mail. The rest are kinds of run that code or a tool starts (`mail-review`, `mail-learn`, `mail-learned`, `mail-refile`, `mail-answer`, `mail-digest`) and go in `mail/nexusai/prompts/`; `interview-start` goes in `nexusai/nexusai/prompts/`. Loaded by name through the plugin loader instead of `resources.files` in `mail_agent.py`.

## 5. An agent file

Anthropic's fields carry the meaning they have in Claude Code. Ours sit under `nexusai`.

```markdown
---
name: mail                       # the id: never changes, never shown. Lowercase and hyphens
description: >                   # for Posty's routing only; written for the model
  Give it work that means reading mail in depth: triaging many emails, re-sorting a
  folder or a month of mail, or learning from past mail.
  Not for moving or marking one email; Posty does that.
tools: [triage, reading]   # jobs (§8) or single tools. Leaving it out means reading tools only
disallowedTools: [draft_reply]
skills: [drafting-replies]       # Anthropic's meaning: preloaded in full at the start
mcpServers: []                   # connectors this agent may use, by name
model: inherit                   # or a model the person has; inherit is the default
effort: medium
maxTurns: 20
nexusai:
  displayName: Mail agent        # the person can rename; the rename is kept on top, in the database
  handle: mail
  role: Reads every new email and pulls out what matters: where it goes, what you need to do and by when, which matter it belongs to, and a draft if it needs a reply.
  mascot: { style: square, seed: mail }
  lead: false                    # exactly one enabled agent has lead: true
  talksToPerson: false
  mayAssignTo: []
  accepts: [person, assign, ask, note]
  readsUntrustedMail: true       # then the loader refuses any tool that sends, deletes or changes settings
---
You look after the person's email on {{agent.session.name}}'s team...
```

- **What starts an agent is not in its file.** A routine starts it (§6), the person talks to it, or another agent hands it work. `runs_on` goes away.
- **`description` and `role` are different readers.** `description` is for Posty choosing who gets the work. `role` is the one line people see.
- **Ids stay as they are:** `session` (Posty), `mail`, `daily-prep` (Brief writer), `interview` (First meeting), and the new `routines`. Ids are never shown, and `session` alone is written in 56 places in 13 files and stored in many tables, so renaming them would be churn for looks. `organizer` is folded into `session` (`docs/AGENT_OWNERS_PLAN.md`). Inside the app, agents from other plugins are `plugin:name` (Anthropic's namespacing); the built-in ones are referred to by their short name, and the loader refuses a second agent with the same short name and the same handle.
- **The person's own agents are the same file**, in their own plugin (§7). A Claude Code, Copilot or Gemini agent file can be pasted: `name`, `description`, `model`, `skills` and the body carry over, `tools` is limited to what §8 allows, and fields not used here are listed as such.

## 6. Skills, connectors, routines

**Skills:** `SKILL.md` exactly as Anthropic writes it: `name`, `description`, `when_to_use`, `disable-model-invocation`, `user-invocable`, `allowed-tools` (read as a list of tools the skill needs, never a grant), `paths` (ignored), `metadata`. What `skills.py` adds today (`needs_tools`, which agents may load it) moves to `metadata.nexusai`. Name and description stay in the prompt; the body comes with `load_skill`, other files with `read_skill_file`, as now.

**Connectors:** `.mcp.json` exactly as Anthropic writes it: `mcpServers` keyed by name, `type` (`http`, `streamable-http`, `sse`; `stdio` later and off by default), `url`, `headers`, `${user_config.KEY}` for secrets. Connectors added on the Connectors page are saved into the person's own plugin's `.mcp.json`, with header values in `secret_store`, never in the file. Which agents get a connector moves from the connector (`audience`) to the agent (`mcpServers`), as in Claude Code. Each connector's tool list is still hashed, and new tools still wait for approval.

**Routines:** `nexusai/routines/<name>.md`, shaped after Anthropic's routine (a name, a prompt, connectors, triggers) with our triggers and Anthropic's names where they fit:

```markdown
---
name: every-weekday-morning
description: Writes the brief each weekday morning.
agent: daily-prep                     # who runs the model step, with that agent's tools only
mcpServers: []
triggers:
  - schedule: { cron: "30 8 * * 1-5" }   # Anthropic's schedule trigger; local time, not UTC
nexusai:
  tell: [{ todayPage: brief }]
---
Write today's brief.
```

```markdown
---
name: on-new-mail
description: Reads each new email as it arrives and records everything in it.
agent: mail
triggers:
  - event: { name: mail.received }      # our events, by their bus names
---
Read this email and record everything in it.     # the body is today's mail-one prompt
```

- **Routines are named by what starts them** (On new mail, Every weekday morning), never by the agent's job, so a routine doesn't read as a second Mail agent. What the agent pulls out of an email is defined once, by the `triage` job and `record_triage`; a richer triage card (To do 4d) adds fields there and the routine doesn't change.

- Trigger kinds: `schedule` (Anthropic's), `event` (an app event, such as `mail.received`, optionally "an email like …" judged by the Mail agent), `check` (a URL or a condition with no model). Anthropic's `api` trigger maps to the planned company-assistant door later.
- **A routine never has tools of its own**; its model step runs as `agent`. This closes today's gap where every schedule is a hidden agent with every tool.
- The person's routines live in their own plugin, made by the Routines agent. Run history and on/off stay in the database.
- Repeating reminders are not routines (To do 13): a reminder fires with no model and is Posty's.

## 7. Where plugins come from, and what wins

| Layer | Where | Who changes it | Trust |
|---|---|---|---|
| **Company** | A folder IT manages: `/Library/Application Support/NexusAI/` on Mac, `C:\ProgramData\NexusAI\` on Windows (Claude Code's managed policy, our name) | IT | Trusted as is |
| **The person's own** | The plugin `yours`, kept in the encrypted database as its files (path and text), written out as a folder only on export | The person, through Posty, the Routines agent or the pages | Reviewed when an agent proposes it (as skills are now) |
| **Installed** | `<Home>/plugins/<name>/`, copied from a marketplace, GitHub, a zip or a folder | The person, through `propose_plugin` | Reviewed in full, pinned to the approved hash; a change on disk turns it off |
| **Built in** | Inside the app | Us, with each release | Trusted, signed with the app |

- **Same name, higher layer wins**, as in Claude Code. The company can replace or switch off a built-in agent, skill or connector, and can add `deny` rules for tools. Within a layer, items are named `plugin:name`, so two plugins can both have a `review` skill.
- **The person's own plugin is a real plugin, stored privately.** Their agents and routines can name people, projects and clients, so they're kept in the encrypted database, not as plain files in Home, and every change goes through a repository with its event, like any other write. The loader reads it exactly as it reads a folder. It can be exported and shared as a folder, which is how a team head hands their routines and agents to the team.
- **Marketplaces** use Anthropic's `marketplace.json` unchanged (`name`, `owner`, `plugins` with `source`: path, `github`, `url`, `git-subdir`, `archive`; `npm` and `command` not used). The company layer can name one marketplace as the only one allowed.
- **State is never in a plugin folder:** on/off, approvals, hashes, renames, run history and secrets are in the database or `secret_store`, keyed by `plugin:name`. Updating a plugin replaces its folder and keeps the state.

## 8. Jobs, tools and ownership

This is `docs/AGENT_OWNERS_PLAN.md` §6, put in Anthropic's field.

- **A job is a named group of tools, defined in code** (`modules/agent/jobs.py`): `reading`, `talk`, `mail-actions`, `drafts`, `tasks`, `reminders`, `folders-and-rules`, `matters`, `triage` (everything `record_triage` holds: folder, status, importance, notify, deadlines, follow-up, matter, suggested tasks, reminders and draft, what was learned, confidence and a question), `brief`, `routines`, `computer`, `team`. An agent's `tools` lists jobs, single tools, or `mcp__<server>__*`.
- **Owned jobs have one maker.** A job marked owned (`triage`, `brief`, `routines`, …) may be listed by only one enabled agent. The loader refuses a second one and says which agent already owns it. Everyone else gets the owner named in the tool error: "That's @mail's job. Hand it over with team_assign."
- **Shared by every agent, never listed:** reading, team tools, `remember`, `list_memory`, `load_skill`, `find_tools`, `save_preference`. Per-run extras stay in code as now (`ask_user` when typing, `update_mail` on a team task, the judging tools when a routine starts the Mail agent on an email).
- **The prompt's "Yours, and not yours"** and Posty's hand-over list are generated from the loaded agents' `tools` and `description`.
- **Preferences are keyed by job** (`docs/PREFERENCES_PLAN.md`), so moving a job to another agent, or replacing an agent through a plugin, moves nothing the person said.

## 9. Instructions and memory are not plugins

Claude Code doesn't load a plugin's `CLAUDE.md`, and we follow it: **what the person wants is never shipped in a plugin.** A plugin brings agents and know-how; the person's words decide how they're used.

- **Instructions** are the `preferences` rows (`docs/PREFERENCES_PLAN.md`), shaped like Anthropic's rules: a text and what it applies to. Anthropic's `paths` becomes `appliesTo`: a job, and optionally an account, sender or topic. A row loads only when the run touches what it applies to, as a rule loads only for matching files. They stay in the encrypted database, with versions and Undo.
- **Company instructions** sit above the person's, as Claude Code's managed `CLAUDE.md` does: a file in the company folder, for things like "never forward outside samsung.com".
- **Memory** is the memory notes, typed with Anthropic's four types (`user`, `feedback`, `project`, `reference`), facts and never orders, as now.
- **Order of what wins** (`system.md`): rules and tool limits (including company `deny`), company instructions, the person's instructions, About the person, what they corrected, the agent's file body, memory.

## 10. Trust

- **Text is reviewed; code is not run.** Skills, agents and routines are text: reviewed in full on install, pinned by hash. Remote MCP servers are reached only after review, with per-tool approval. Local MCP servers (`stdio`), hooks (`hooks/hooks.json`), `bin/`, commands, LSP servers, monitors and output styles are read and shown on review as "not used here".
- **An agent file can't widen its own reach.** Its `tools` can't name an owned job someone else holds, `readsUntrustedMail: true` refuses tools that send, delete or change settings (Rule of Two, `docs/AGENT_HARNESS_PLAN.md`), and the guard and approvals apply to every agent as today. A routine has no tools of its own.
- **Secrets never live in a plugin.** `userConfig` fields with `sensitive: true` are asked for on install and kept in `secret_store`; a literal key in a plugin is refused on review.

## 11. Keeping a weak model's prompt small

- **Two steps for everything**, as Claude Code does: names and one-line descriptions are always there; bodies come when needed (`load_skill`, `find_tools`, the agent file only for the agent that runs).
- **A cap on what's always shown.** Skill and agent descriptions together get a fixed share of each agent's prompt (Claude Code uses 1% of the context). Past it, the least-used descriptions are dropped first and names stay. A test fails if the built-in plugins alone go past half the cap.
- **`skills` in an agent file preloads in full**, so use it only for short skills the agent needs on every run.
- **Instructions load by what they apply to** (§9), not all at once.

## 12. What changes in the code

| Today | After |
|---|---|
| `cards.py` reads `agents/*.toml`; `prompts_builder.py` reads `prompts/<id>.md` | `plugins.py` (new, in `modules/agent/`) loads every layer; `cards.py` reads agent files from it. One contract, `AgentDefinition`, replaces `AgentCard`'s source |
| `skills.py` reads `shipped_skills/` and the person's skill folders | Reads skills from the loaded plugins. Approval and pinning stay, keyed `plugin:name` |
| `connectors` module keeps servers in the database | Reads `.mcp.json` from loaded plugins; the Connectors page writes the person's plugin. Secrets stay in `secret_store` |
| `ORGANIZER_ONLY`, `MAIL_AGENT_ONLY`, `BRIEF_AGENT_ONLY`, `allowed_for` in `tools.py` | `jobs.py` plus each agent's `tools` |
| Schedules become hidden agents (`scheduled.toml`) | Routines run as their `agent`; `scheduled.toml` goes |
| `mail_agent.py` started from the mail pipeline; its prompts read from `prompts/triggers/` | Started by the On new mail routine through `SessionRuntime.dispatch`, same as now underneath; prompts from the `mail` plugin |
| Each schedule and event trigger the person made is a hidden agent (`schedule-<id>`, `trigger-<id>`) | Unchanged until Routines (step 7); step 1's comparison test covers them |

Contracts first, as always: `Plugin`, `AgentDefinition`, `SkillDefinition`, `RoutineDefinition`, `PluginLayer` in `contracts/`, then `npm run contracts`.

## 12b. Seeing what's happening

- **A broken file never stops the app.** The loader skips the item, keeps the reason, and the Plugins and Agents pages show it: "Couldn't load `agents/kite.md`, line 4: `tools` names `triage`, which @mail owns." The rest of the plugin still loads, unless its `plugin.json` itself is broken.
- **Load-time checks** catch two owners of one job, an agent with `readsUntrustedMail` and a sending tool, an unknown job, a skill or connector an agent names that doesn't exist, and two agents with the same handle.
- **Changes are events, not polling.** Adding, changing, switching or removing a plugin emits `plugins.changed`; caches rebuild, open screens refresh over SSE, and the next run uses the new set. A run already going finishes on the set it started with.
- **Every run records what it was built from:** each agent, skill, routine and prompt by `plugin:name` and file hash, and what started it (a routine, a hand-over, the person). Kept with the trace, next to `skill_loads`, so "why did it do that?" points to the exact text used.
- **"Everything it's told, in order"** labels each section with the file it came from.
- **The Routines page** lists each run: what started it, which agent ran, what it did, and how it ended.
- **The Windows build** bundles `plugins/` like `shipped_skills/` today, and desktop CI checks the packaged app loads all five built-in plugins.

## 13. Steps

Each step is small and shippable, tested with the fake model. No real-model eval without asking. Screen changes need a mockup first.

1. **The loader, same behaviour.** `plugins.py` reads built-in plugins. The six cards and their prompts become `agents/*.md` in the built-in plugins; `shipped_skills/` and `prompts/triggers/` move into them. Load errors kept and checked (§12b), run records, and the packaged-app check in desktop CI. A test compares every agent's tools, prompt and card before and after, the person's agents and schedule agents included: no change.
2. **Jobs and one owner** (`docs/AGENT_OWNERS_PLAN.md` steps 1–3): `jobs.py`, `tools` in the agent files, the Organizer folded into `session`, the gaps closed.
3. **Generated sections:** "Yours, and not yours", Posty's hand-overs from `description`, the description cap.
4. **Personalization** (`docs/PREFERENCES_PLAN.md`), keyed by job, loaded by `appliesTo`.
5. **The person's own plugin:** their agents, skills, connectors and personal skill folders move into `yours` in the database; paste a Claude Code agent file; export as a folder.
6. **Install plugins** (`docs/PLUGINS_PLAN.md`: review card, `userConfig`, headers, marketplaces). Mockup first.
7. **Routines** (To do 1 and 13): `nexusai/routines/`, the Routines agent, the brief and judging as built-in routines, `scheduled.toml` retired.
8. **The company layer:** the managed folder, company instructions, `deny` rules, one allowed marketplace. With the Windows rollout.

## 14. Decided here

Recommended, and taken as the plan unless the person says otherwise:

1. Anthropic's file and field names, ours under `nexusai` only.
2. Built-in agents, skills and routines ship as plugins in the same format.
3. The person's own things are a plugin, `yours`, kept in the encrypted database in the same file shape; state stays in the database and secrets in `secret_store`.
4. Routines are files in `nexusai/routines/`, never agents; the brief and judging new mail are built-in routines.
5. Instructions and memory stay out of plugins, in the encrypted database.
6. Hooks, local MCP servers and anything else that runs code: read and shown, not run.
7. Ids stay as they are (`session`, `mail`, `daily-prep`, `interview`, plus `routines`).
8. The Mail agent's job is `triage`: everything `record_triage` holds. Routines are named by what starts them.

## 15. Build order for this iteration (2026-11-26)

Agreed 2026-11-26: steps 1–3 and Routines (step 7, with repeating reminders) are built in this iteration. Installing plugins (step 6) and the person's own plugin (step 5) come next. Each phase is its own branch, merged only when `make check` passes; nothing a phase doesn't name changes behaviour.

**What depends on what is changed** (inventory, 2026-11-26):

| Changed | Read by |
|---|---|
| Agent cards (`agents/*.toml`) | `cards.py`, and through it `prompts_builder`, `knowledge`, `registry`, `team`, `runtime` (run trace keeps `card.version`), `tools`, `triggers`, `cockpit`, `monitor`, `context`, `trace`, `work_tools`, `api/app.py`; the Agents, Team and Map screens through `AgentCard` and `AgentEntry` |
| Agent prompts (`prompts/<id>.md`) | `prompts_builder.agent_prompt` (also hashed into `knowledge.decision_context_version`, so a changed byte would re-judge mail: bodies move byte for byte), the Prompts tab (`module.py`, built-in text shown read-only, the person's extra text in `<Home>/prompts/agents/<id>.md`) |
| `shipped_skills/` | `skills.py` (shipped skills are trusted; approvals keyed by name) |
| `prompts/triggers/` | `mail_agent.py` (`resources.files`), and through it `triggers.py` |
| `schedules`, `agent_triggers` | `scheduler.py`, `triggers.py`, `cards.py` (each person-made schedule or trigger is an agent `schedule-<id>` / `trigger-<id>`, and their chats were moved to those ids by `agent_cards_yours_001`), `registry.py`, `cockpit.py`, `mail_agent.py`, `work_tools.py`, `module.py`; Schedules screen, `TriggerForm`, `RunOptions`, `AgentRunSettings`, `usePlannerCounts` |
| Reminders (`planner` module) | `work_tools.py`, Reminders screen, the time check in `scheduler.py` |

**Phases:**

A. **The loader, same behaviour.** `modules/agent/plugins.py` reads built-in plugins from `modules/agent/builtin_plugins/<plugin>/` (root `plugin.json`, no dot-folders, so packaging needs nothing new). Cards and prompts become `agents/<id>.md`; `shipped_skills/` and `prompts/triggers/` move in. Before anything moves, a golden snapshot of every card, prompt body, skill and trigger prompt is taken from today's code and committed as a test fixture; the new loader must reproduce it exactly. Load errors kept, not raised, for anything but a built-in (a broken built-in still fails start-up and CI, as a broken card does now).

B. **Jobs and one owner.** `jobs.py`; each agent's `tools` lists jobs; `ORGANIZER_ONLY`, `MAIL_AGENT_ONLY`, `BRIEF_AGENT_ONLY` replaced; the Organizer folded into Posty (its sessions and stored references pointed to `session`, its prompt lines into the `tasks-and-reminders` skill); the gaps in `docs/AGENT_OWNERS_PLAN.md` §2 closed. Tests: a walking test over every tool; "remind me at 5" done by Posty in one run.

C. **Routing and checks.** `description` on every agent; "Yours, and not yours" and Posty's hand-overs generated; the description cap; tool errors name the owner; run records (`plugin:name` and hash per run); the done-check when a team task closes.

D. **Routines, backend.** A `routines` table owns its triggers: the existing `schedules` and `agent_triggers` rows gain a `routine` column and keep running as they do (next run, catch-up, `trigger_runs`, token limits, context modes), so nothing about timing changes. Built-in routines come from `nexusai/routines/*.md` in the plugins and are matched to today's rows: On new mail (`agent_triggers` `mail-received`), Every morning (`schedules` `mail-brief`, still daily at 08:30 unless the person changed it), Inbox review (`mail-review`), Mail agent hourly (`mail-hourly`, off). The person's schedules and triggers become their routines, run as Posty with Posty's tools instead of a hidden agent with every tool; their chats and history stay. The Routines agent (`routines` plugin) with its skill and tools. Today's contracts (`Schedule`, `Trigger`) keep being served until the Routines page is rebuilt, so the current screens keep working.

E. **Repeating reminders (To do 13).** Every N minutes or hours, chosen weekdays, a daily window, an end date; one notification per firing with no model; a schedule whose prompt is only "remind me…" is refused toward the reminder tool.

F. **Screens, after mockups are approved:** the Agents page, "who made it", the trace's sources, the Routines page and the Routines agent's setup card. Until then the existing screens stay and read the same contracts.

The NexusAI guide (To do 14) and plugin installing follow this iteration.

**Status, 2026-11-26:** A built and committed (`706a2af`), B built and committed (`a7a6c1a`), E built (repeating reminders). Changed from the text above while building: the Organizer's lines went into Posty's prompt directly rather than a `tasks-and-reminders` skill, since a weak model reads a prompt every time but must choose to load a skill; restricted agents' tool lists stay in code for now (a test compares them with the old ones), and `tools` in agent files is for plugin agents later; the weekly Inbox review isn't a built-in routine (it was removed in `agent_no_mail_suggestions_001`).

**D, built 2026-11-26:** the `routines` plugin and its Routines agent (`@routines`), which owns setting up, changing, running and removing routines (`jobs.py`); Posty hands that work over and its prompt says so. No separate skill: its rules are in its prompt, for the same reason as above. The routines list stays the existing `agents.list` (the Agents map already lists every schedule and trigger with its state, next and last run), extended when the Routines page is built (F) rather than a second query now. Left for F, with the screens: the built-in routine files and "built in" on each entry, the person's schedules running as Posty instead of a hidden agent, and the sidebar number counting only what needs a look.

**C, built 2026-11-26:** Posty's hand-over table is generated from each agent's `description` (`{{handovers}}`, `cards.handovers`); each agent's "Who you are" says which jobs are its alone and whose the others are; a team report from a run that changed nothing is flagged to the giver; each run's record names its plugin. No limit on descriptions yet, as decided.

**F, built 2026-11-26** from the approved mockups: the Agents page in two columns (job, what starts it, what it can't do, skills, plugin, what it's told, recent work); Schedules renamed Routines, the person's own first and everything built in folded away, the morning brief switchable there; the sidebar number counts only routines that need a look; the richer triage card with suggestions kept or dismissed in place; suggested tasks say Keep and Dismiss and name the Mail agent; each answer says which agent and plugin built it. Differences from the mockups: a routine's details stay in the existing drawer rather than a side panel; the triage card shows the agent's question without answer buttons (answering still happens in chat); the Agents page has no Connectors row yet, since connectors aren't attached per agent until plugins are installable.

Still to do from this plan: the person's own schedules running as Posty with Posty's prompt (today they keep the routine prompt and Posty's tools), built-in routine files, installing plugins (step 6), the person's own plugin (5), and the company layer (8).
