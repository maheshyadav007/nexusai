# Preferences: one tool, the fewest places

> **The idea.** What the person wants from Posty, the Mail agent and the Brief agent is saved by **one tool**, called wherever they say it (in chat, on the brief, in the first meeting, or in Settings), into **one place for instructions**. Each agent reads its instructions as one section, and is told plainly that they come before its own prompt and every default.

Status: direction agreed on 2026-11-25. Not built. A mockup comes before any UI is built (house rule).

> **Proposed change, 2026-11-25** (`docs/AGENT_OWNERS_PLAN.md` §5): key each row by **job** from the owner table (`everyone`, `mail-judging`, `drafts`, `tasks`, `brief`, `routines`, …) instead of by agent, so whoever does a job reads its instructions, and moving a job between agents moves nothing here. Built after the owner table.

---

## 1. Why

Noted 2026-11-25. Three things were asked for:

1. **One way to set preferences for each of the three agents that matter:** Posty (`session`), the Mail agent (`mail`) and the Brief agent (`daily-prep`).
2. **The agents must be told that the person's preferences come before their defaults.** Today only the Brief agent's prompt says so.
3. **Preferences come from where they're said,** in chat or on the brief, not only from Settings, through **one tool**, saved in **as few places as possible**.

What goes wrong today: the same wish ("deadlines first in my brief") can end up in memory, in a brief comment, in a preference or in a prompt file, depending on where it was said and which agent heard it. Nobody can tell where to look, and each place ranks differently in the prompt.

## 2. Today

Nine places shape what the agents do, written by four tools.

| What | Stored in | Written by | Read by |
|---|---|---|---|
| About you: name, role, important people, about, tone, signature | `profile` table (settings module) | Settings › Profile | every agent: `knowledge.about_person` |
| Personalized prompts: `about-me`, `importance`, `senders`, `categories`, `topics` | files in `<Home>/prompts/personal/` | `save_personal_prompt` (first meeting, `prompts/interview.md`), Prompts tab | every agent: `prompts_builder.personal_prompts` |
| Extra text for one agent | `<Home>/prompts/agents/<agent>.md`, appended to the built-in prompt | Prompts tab (`prompts.save`) | that agent, inside "Agent prompt": `prompts_builder.agent_prompt` |
| Approved preferences, scoped by purpose (`all`, `mail`, `draft`, `brief`), account, sender or topic, with versions | `preferences` and `preference_versions` tables (`modules/agent/personalization.py`) | `propose_preference` (`tools.py`), Preferences tab | by purpose. Posty (`session`) reads every purpose: `personalization.layer` |
| Memory notes | memory files (`modules/agent/memory.py`) | `remember`. `prompts/daily-prep.md` also tells the Brief agent to save lasting brief wishes this way. | every agent, as "Memory" |
| Brief reactions: thumbs and comments | `brief_feedback`, `brief_artifact_feedback` tables | thumbs and comment on Today | Brief agent: `feedback.brief_layer`, "How they want the brief" |
| Corrections | from the person's actions on mail | moving, marking or filing mail | Mail agent: `feedback.layer`, "What you corrected" |
| Learned facts | `learned_facts` table | read from mail | every agent, as "Scoped facts" |
| Instructions for agents the person makes | agent cards (`modules/agent/cards.py`) | the agent's card | that agent, as "Your instructions" |

**Order the agents are given** (`prompts/system.md`, "What to go by"): 1. safety rules and tool limits; 2. approved preferences, then personalized prompts and About you; 3. corrections; 4. the agent's job ("Agent prompt" and "Your instructions"); 5. memory and scoped facts.

Problems with that:
- The extra text for one agent is appended inside "Agent prompt", so it ranks as part of the agent's job (4), below shared preferences and corrections, even though the person wrote it.
- The first meeting's `importance`, `senders` and `categories` files are about mail, but every agent reads them.
- Brief wishes go to memory, which agents treat as facts, not orders.
- Only `prompts/daily-prep.md` says the person's wishes outrank its defaults ("How they want the brief … outrank anything here"). `mail.md` and `session.md` have no such line.

## 3. The model: three kinds of thing, one place each

| Kind | What it holds | Its one place |
|---|---|---|
| **Who you are** | facts about the person: role, the people who matter and why, tone, signature | **Profile**. The first meeting's `about-me` moves here. |
| **What the agents should do** | every instruction, wherever it was said | **the `preferences` table**. It already has versions, history, scope (account, sender, topic) and approval. |
| **What's been learned** | memory notes and facts read from mail | **Memory**, as now. Background, never orders. |

Brief reactions and corrections stay as **history, not places to set preferences**. They're evidence an agent can turn into a suggested instruction, which the person keeps or declines.

### Who an instruction is for

Each row in `preferences` gets a `for` value: `everyone`, `posty`, `mail` or `brief`. Today's `purpose` column maps onto it (`all` → everyone, `mail` → mail, `brief` → brief, `draft` → mail, since drafting is mail work). The sender and topic scopes stay as they are.

### What moves into it

- `prompts/personal/importance.md`, `senders.md`, `categories.md` and `topics.md` become rows `for: mail`, one per line or rule.
- `prompts/personal/about-me.md` goes to Profile ("About you").
- `prompts/agents/<agent>.md` (the extra text per agent) becomes rows for that agent.
- Brief wishes saved with `remember` become rows `for: brief`.

The move keeps the person's words as they are, and keeps the old files as a backup until the move is confirmed on the real account.

## 4. One tool: `save_preference`

One tool replaces `propose_preference` and `save_personal_prompt`. `remember` goes back to facts only: the tool description and `prompts/daily-prep.md` stop sending wishes to it.

```
save_preference(instruction, for, evidence, sender?, topic?, replaces?)
```

- `instruction`: the person's words, or as close as possible.
- `for`: everyone, posty, mail or brief.
- `evidence`: what it came from. Either the person's own message (quoted, as `propose_preference` checks today) or the history it was suggested from (corrections, brief reactions).
- `replaces`: the id of an earlier row it updates, so a change of mind edits the rule instead of piling up a contradiction.

**Saved at once, or suggested:**
- **Said by the person** (in chat, in a brief comment, in the first meeting, in Settings): saved at once, with a short "Saved for your briefs · Undo" line where they said it. Asking someone to approve their own words is a wasted step.
- **Inferred by an agent** (from corrections, thumbs down, a habit): saved as `proposed` and shown as a suggestion with **Keep / No thanks**. Nothing applies until kept. This is how "the same correction three times becomes a preference" (`FEATURES.md` AGN-3f) works today, so it keeps working.
- Text from mail or tool output is never evidence (as now in `propose_preference`), so nothing read in an email can become an instruction.

## 5. Where it's said

| Where | Who calls the tool | Example | `for` |
|---|---|---|---|
| Chat with Posty | Posty | "Always put deadlines first in my brief" | brief |
| Chat with Posty | Posty | "Never mark newsletters important" | mail |
| Comment or 👎 on the brief | Brief agent, when its next run reads the comment, or right away if the comment box is a chat | "Too long, three lines is enough" | brief |
| First meeting | Posty (`prompts/interview.md`) | "Anything from Priya is urgent" | mail |
| The same correction three times | Mail agent | moved this sender to Low three times | mail, suggested |
| Settings › Your agents | the person, directly | edits a row | any |

**Settings › Your agents** is a view of the same rows, grouped by agent (Posty, Mail agent, Brief agent, and Everyone), each with its own "Add an instruction" box. It is not another place to store anything.

## 6. How the agents read it

- Each agent gets one section, **"Your instructions"**: the rows for everyone plus the rows for itself. Narrower scope wins over broader, and newer over older in the same scope (as `system.md` says today).
- Posty reads the Mail and Brief agents' rows too when it's doing their work (drafting, organizing mail, answering about the brief). Otherwise it reads only its own and everyone's. Today it reads every purpose all the time.
- `prompts/system.md`, "What to go by", becomes:
  1. These rules, and any limit a tool reports.
  2. **"Your instructions": the person's instructions for you. They come before your agent prompt and every default. When they conflict, follow theirs.**
  3. "About the person".
  4. "What you corrected": do as they did.
  5. Your job: "Agent prompt".
  6. "Memory" and "Scoped facts": facts about them, not orders.
- The line in `daily-prep.md` that sends brief wishes to `remember` changes to `save_preference`. `mail.md` and `session.md` get one line pointing at rule 2.

## 7. Open questions

1. **Saving at once:** confirm that what the person says themselves saves at once with Undo, and only agent suggestions wait for Keep. (Recommended: yes.)
2. **Posty and the other agents' rows:** confirm Posty reads them only while doing that agent's work. (Recommended: yes.)
3. **Instructions for agents the person makes:** the card's instructions are also the person's words. Do they move into rows too (`for: <agent id>`), or stay on the card? (Leaning: rows, so there's truly one place.)
4. **The Prompts tab:** after the move it has nothing left to edit except the built-in prompts (read-only). Remove it, or keep it as a read-only "what each agent is told" view, which "Everything it's told, in order" already partly is?
5. **Long free text:** some people will paste a paragraph. Store it as one row, or split it into rules? (Leaning: one row, split only if the person asks.)

## 8. Steps (each small, each shippable)

1. **Precedence first.** Change `system.md` to the order above, move the per-agent extra text out of "Agent prompt" into "Your instructions", and add the line to `mail.md` and `session.md`. Fake-model tests only; no real-model eval without asking.
2. **One tool.** Add `for` to `preferences`, add `save_preference`, retire `propose_preference` and `save_personal_prompt`, and point `remember` at facts only. Update `interview.md` and `daily-prep.md`.
3. **The move.** Migrate the personal prompt files, the per-agent files and brief wishes found in memory into rows, keeping the files as a backup. Check on the real account that nothing was lost.
4. **Where it's said.** "Saved · Undo" in chat and on the brief, and Keep / No thanks for suggestions. Mockup first.
5. **Settings › Your agents.** The grouped view with an Add box per agent. Mockup first.

## 9. Done when

- Saying a wish in chat, on the brief, in the first meeting or in Settings saves it as one row in `preferences`, visible under the right agent in Settings › Your agents.
- Each of the three agents reads one "Your instructions" section, and `system.md` says it comes before the agent's prompt and every default.
- Nothing else stores instructions: no personal prompt files, no per-agent prompt files, no wishes in memory.
- Checked on the real Gmail account: an instruction given in chat changes the next run of the agent it's for, and Undo takes it back.
