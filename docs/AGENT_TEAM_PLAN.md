# Agent team plan

How the NexusAI agents work as a team on a low-capability model, so the harness carries the quality: focused agents with short instructions and few tools, Posty leading, tool results that say what to do next, and memory noted during the work. Agreed with the person on 2026-11-17. Builds on the [agent harness plan](AGENT_HARNESS_PLAN.md), which built the cards, router, tasks, skills, safety and monitoring.

## Why

Reviewed on 2026-11-17 against the code, with the fake model:

| Problem | Evidence |
|---|---|
| Posty does nearly everything itself | About 80 tools, 26 shown at the start (about 3.2K tokens of schemas), about 3.2K tokens of instructions on an empty Home. `session.md` says to do the work yourself by default. Only @mail and @brief take tasks |
| Routing is judgement inside a long prompt | Only `@handle` is decided in code |
| Agents are told about tools they don't have | `system.md` goes to every run (`prompts_builder.py`), so judging one email is told to use `remember`, `list_memory` and `find_tools`, which `TRIAGE_TOOLS` doesn't include. `mail.md` describes all five run modes on every email |
| Tool errors make repeats likely | Bad arguments return LangChain's default, `Error invoking tool 'create_tasks' with kwargs {...} … Field required`: the failed call repeated word for word, without the right shape. An unknown tool returns all ~80 names. The `team_assign` error lists @meeting and @posty, which can't take tasks |
| Handing work over is heavy | `team_assign` needs objective, expected output and done criteria. In the eval, 6 Luna used 19 to 21 calls and 84K to 130K tokens on the hand-over case, and filed the mail twice |
| Memory and corrections are partial | Saving depends on the chat model (`KNOWN_PROBLEMS.md`). Recall is by shared words (`memory.py`). "What you corrected" goes only to the Mail agent |
| No measure on a weak model | 5 team cases, one try each, on mid and large models |

## What frontier practice says

- A lead that routes, with each specialist offered as one simple tool described in a line ([OpenAI Agents SDK handoffs](https://openai.github.io/openai-agents-js/guides/handoffs)).
- Split into agents only where context pollution or separate work makes it pay. A specialist gets a self-contained task and returns a short result ([Anthropic: building multi-agent systems](https://claude.com/resources/articles/building-multi-agent-systems-when-and-how-to-use-them)).
- Errors go back to the model so it can correct itself, but repeating the failed call word for word makes small models repeat it ([Feedback That Backfires](https://arxiv.org/pdf/2608.23651), [verbatim failure records](https://agentpatterns.ai/patterns/anti-patterns/verbatim-failure-records/)).
- Memory is written during the work, and optionally in a background review ([LangMem](https://langchain-ai.github.io/langmem/background_quickstart)). We do the first now and hold the second.

## The plan

Order: 0, 1, 2, 3, 4. After each step, rerun the yardstick on the fake model, and on the weak model when the person agrees ([no real-model evals without asking](EVALS.md)).

### Step 0: a yardstick of 50 cases

Set at Samsung R&D Bangalore, on a Beyond 5G / 6G research team: 3GPP Rel-20/21 work items, AI-RAN, NTN, O-RAN, ISAC, patents, testbeds and operator trials with Jio and Airtel. People are Bangalore colleagues, HQ in Suwon and Seoul (KST, Korean-English mail) and outside partners. About 70% of the cases sit above manager and tech lead level.

| Level | Situations |
|---|---|
| Group Head, Director, VP | Budget asks, quarterly reviews, headcount, HQ directives with deadlines, an action hidden in a broadcast |
| Principal Engineer, Tech Lead | Standards contribution deadlines, a delegate's review requests, patent committee, an operator escalation |
| Manager and peers | Hiring loops, approvals, project status, a colleague asking for help |
| Noise | HR and IT broadcasts, phishing look-alikes, build mail, conference spam |

| Group | Cases | Checks |
|---|---|---|
| Mail judging | 20 | Is it asking them something, importance, notify |
| Posty alone | 12 | Search, drafts, a question across mail and documents |
| Hand-over and routing | 10 | Filing, rules, tasks from mail |
| Asking the person | (within the above) | Vague or unfindable requests end in `ask_user`, never a guess |
| Memory and corrections | 5 | A correction is followed on the next run |
| Recovery | 3 | A tool fails and a path to success exists |

Each case runs 3 times and counts only if it passes every time. Built and proven on the fake model first.

### Step 1: clear prompts and tool results that say what to do next

- Each agent's system prompt is built from the tools it has: no sections about tools it lacks. `mail.md` gets only the run mode that applies.
- Every tool result says what happened and the next move:
  - Bad arguments: the field, the expected shape and a one-line example. Never the failed arguments.
  - Unknown tool: the three closest names and `find_tools`.
  - Nothing found: a next move, such as `semantic_search` or searching by sender.
  - Something similar exists: show it and the choices, such as "'Finance' (id 4) exists: `update_category`, or pass `new=true`".
  - Refused or blocked: why, and what the person can do.
- `team_assign` works with just an objective. Defaults fill the rest.

### Step 2: the team

| Agent | Owns |
|---|---|
| Posty | Leading, routing, checking results, searching mail and documents, drafting replies, and asking the person |
| Mail | Judging, filing, categories, rules |
| Organizer (new) | Tasks, reminders, schedules |
| Brief | The brief on Today |

- Posty hands over with one simple `route(agent, objective)`. A quick job runs in the same turn and returns a short result. Long work stays a background task.
- Posty loses the tools that now belong to specialists.
- A big or complicated search or draft can move to its own run later, only if the yardstick shows Posty failing at it.

#### Asking the person

Kept as it is. Every question an agent asks, with `ask_user` or the Mail agent's `question` on a judgement, lands in "Waiting on you" on Today with Answer and Skip, and the agent carries on with the answer or its best guess. Posty is told to ask whenever a request is vague, has more than one likely meaning, or it can't find what was meant after searching, offering options built from what it found.

### Step 3: memory noted during tasks

The background memory review is on hold.

- Every agent that talks to the person can save memory. The Mail agent uses the `memory` field of its judgement.
- `remember` replies with exactly what was saved, or that it was already known.
- If a reply says "noted" or "I'll remember" without a save in the same step, the harness asks the agent to save it, once.
- Corrections from any agent are kept, and each agent is given the ones about its own work.
- Memory is recalled by meaning, with word overlap as the fallback.

### Step 4: carrying on after failure

- A failed or blocked run returns what was done, what wasn't, and the next step. Posty continues from that.
- The same failing call twice gets "this failed twice; try X, or ask the person".

## Progress log

- 2026-11-17: plan agreed.
