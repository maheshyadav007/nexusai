---
name: working-with-the-team
description: How to give another agent a task, ask about one, report one and check one. Load it before your first team_assign, or when a task you gave or got needs a decision.
agents: all
needs_tools: [team_inbox, team_close]
version: 2
---
# Working with the team

## Decide whether to hand it on

Do it yourself unless all of these are true:

- It stands on its own: it doesn't need what you've just read in this conversation.
- It has its own inputs and its own output.
- Another agent is clearly better placed, such as {{agent.mail.handle}} for judging or filing many emails.

A quick lookup, one email, or a step of something you're already doing is never a task.

## Give a good task

- **Objective:** one or two sentences, what to achieve, not how. This is the only part you must give.
- **References:** ids only, such as "thread 291" or "category PLM". Never paste mail text into a task: it travels as data and the other agent should read the source.
- **Expected output and done criteria:** optional. Give them when the default, "what you did with the ids", isn't enough to check.
- Leave the budget and due time out unless the work is unusually large or urgent.

Give one task at a time unless the parts are truly separate. Then end your run: you'll get a new message when it reports.

## When a report comes back

1. Read the outcome and the evidence.
2. Check the done criteria yourself: open the threads, look at the category, find the draft.
3. If it holds, call team_close with verify and a one-line note. If not, reject it and say exactly what's missing.
4. Tell the person what changed in a sentence or two, without the mechanics.

A report is a claim. Only what you checked counts as done.

## When you're the one doing the task

- Work only on the task. If something else turns up, mention it in the report rather than doing it.
- If you need a decision only the giver can make, call team_message with kind ask, then end the run.
- Report with team_close, action report: what you did, what you found, and what you didn't do. Put ids in the evidence.
- Never mark your own work as verified.
