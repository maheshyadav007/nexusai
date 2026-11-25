# What others do, and where NexusAI adds most at work

Researched 2026-11-25: Littlebird, Linear, Scape, and the AI email tools (Superhuman, Shortwave, Fyxer, Copilot in Outlook). Research only; anything taken goes through its own plan and, for UI, a mockup.

## Contents

1. [Each product: what it is, its edge, why people use it](#each-product)
2. [Patterns that repeat](#patterns-that-repeat)
3. [Where NexusAI is different](#where-nexusai-is-different)
4. [Most value at work, ranked](#most-value-at-work-ranked)
5. [Sources](#sources)

## Each product

### Littlebird: "the always-on assistant"

- **What:** a Mac and Windows app that reads the text of the window you're on every few seconds (Accessibility permission; skips password fields and password managers) into a private index, so you can ask about anything you've seen. Plus meeting notes without a bot joining the call, and Routines.
- **Routines:** prompts that run daily, weekly or monthly, are made by describing them in chat, email their result, and can be replied to. Since October 2026 an email can start a Routine.
- **Morning brief** you can reply to; meeting prep made from your history.
- **Actions:** Gmail drafts but never sends; calendar events can be made and moved.
- **Integrations:** Gmail, Outlook, Calendar, Drive, Notion, Slack, Linear, Teams and more. Offers its own MCP server so other AI tools can use its memory.
- **Privacy:** the app runs locally but memory is stored in AWS. Pause, per-app and per-site exclusions, delete by time range.
- **Price:** free tier (5 routines), Plus about $17–20 a month, Team $17 a seat.
- **Edge / why people use it:** no setup. It already knows what you've been doing, so you don't explain context. Routines and the brief bring the work to you.

### Linear: the fast, opinionated work tracker, now with agents

- **Linear Agent** (March 2026): chat grounded in the team's issues and plans, reachable by a shortcut, in comments, Slack and Teams. A useful conversation can be **saved as a skill**.
- **Loops:** agent jobs started by a change (an issue enters triage, a project moves, a Slack or GitHub event) or a schedule. Built from templates or "save as template", a reasoning level per loop, a run history with Resume and Run again, and **spend limits** per workspace, person or loop.
- **Triage Intelligence:** for each new issue, finds duplicates and related ones and suggests labels, owner and project. Each suggestion sits apart from what people set, shows its reason on hover, and the person can see the full thinking. Autonomy grows by type: suggestions first, opt in to auto-apply for a kind of suggestion once it's trusted.
- **Agents as teammates:** work handed to an agent stays assigned to the person; an agent's comment says who wrote it.
- **Edge / why people use it:** speed (anything slower than a few hundred milliseconds is treated as a bug), one opinionated way of working, keyboard first, and AI that lives where the work already is instead of a separate tool.

### Scape

The name covers two products, and directory sites mix them up:
- **scape.work:** a Mac app for developers to build "playbooks" and hand them to agents that run in parallel. Reviewers like that recurring work becomes a playbook they run instead of re-prompting each time. Complaints: Mac only, hard to set up.
- **scape.app:** an AI CRM that collects a team's email and meeting notes and drafts replies.

Only the first has real reviews. The lesson that carries over: **people value turning repeated prompts into one saved, named routine**.

### AI email tools

| Tool | Known for |
|---|---|
| Superhuman | Speed and keyboard; works with Outlook |
| Shortwave | AI search and grouping the inbox; Gmail only |
| Fyxer | Meeting notes and follow-ups; drafts in your voice; strong on compliance claims |
| Copilot in Outlook | Built in where corporate mail already is; weak at team workflows |

Reviewers pick these by one strength each, and by **which mail system they work with**. None of them works with a company's own mail server.

## Patterns that repeat

1. **Routines started by events, not only by time** (Littlebird since October, Linear Loops). With templates, run history, retry, and a cost limit.
2. **Save what worked:** a good chat becomes a skill (Linear), a repeated prompt becomes a playbook (Scape) or a routine (Littlebird).
3. **Suggestions first, autopilot by type once trusted,** with the reason visible on each suggestion (Linear).
4. **Meetings are the second inbox:** prep before, notes after, follow-ups from both (Littlebird, Fyxer).
5. **Live where the work is,** and offer an MCP server so other AI tools can use what you know (Littlebird, Linear).
6. **Drafts, never sends** without the person (Littlebird, and ours).

## Where NexusAI is different

- **Works with the company's own mail server** (POP3 and the corporate setup), which none of the tools above does. This is the opening at work.
- **Data stays on the machine,** in an encrypted Home. Littlebird keeps memory in the cloud. For a company this matters more than any feature.
- **Built to work on a weak model,** so cost and policy limits on models don't block it.
- **Matters:** mail grouped into the pieces of work it belongs to, with state. Closest to Linear's issues, but made from mail by itself.

## Most value at work, ranked

Ranked by how much it helps a person at a company each day, given what NexusAI already has.

| # | Idea | Taken from | Why it pays at work | Fits into |
|---|---|---|---|---|
| 1 | **Routines started by mail, with templates, run history and a cost limit** | Littlebird, Linear Loops, Scape | Most repeated work at a company starts with a mail (a report request, a weekly status, an approval). A limit protects the model allowance | Routines (To do 1): add mail triggers, templates, run history, Resume/Run again, a limit per routine |
| 2 | **Meeting prep from mail** | Littlebird, Fyxer | Company days are meetings. Invites already arrive as `.ics` in mail; the matter and its threads are the prep: who, what's open, what was promised | New item. No recording; prep only, from what's already here |
| 3 | **Company tools through plugins** (issue trackers, wikis, internal systems over MCP) | Linear, Littlebird integrations | Mail mentions tickets and pages; seeing them next to the matter saves switching | Plugins (To do 11): the first plugin to prove should be a company tool |
| 4 | **Reasons on every suggestion, autopilot by kind once trusted** | Linear Triage Intelligence | People at work won't hand over mail until they see why. Turning on "file these by itself" for one kind at a time builds that trust | Triage card (4d), and Preferences (7) for the opt-in |
| 5 | **Save a chat as a skill or routine** | Linear, Scape, Littlebird | The person teaches once and reuses; nothing new to learn | Skills (built) and Routines (1): a "Save as routine" / "Save as skill" step in Posty |
| 6 | **Follow-up chasing as a ready routine** | Fyxer, Littlebird | "Waiting on others" already exists; a weekly "who owes me what" with drafts to nudge is a template for #1 | A template in Routines (1) |
| 7 | **Reply to the brief** | Littlebird | The brief becomes a conversation: "push that to Friday", "done" | Brief lines Done and Dismiss (4f), then reply in Posty |
| 8 | **NexusAI as an MCP server** for the company's coding assistants | Littlebird, Linear | Developers can ask their coding tool about a matter. Needs a security review first; later | Later, after Plugins |

Not recommended at work: **reading the screen all the time** (Littlebird's core). Company security policies are likely to forbid it, and Posty already sees what the app shows.

## Sources

- Littlebird: [Facts](https://littlebird.ai/facts), [Changelog](https://littlebird.ai/changelog), [App Store](https://apps.apple.com/us/app/littlebird-ai/id6737920045), [Product Hunt](https://www.producthunt.com/products/littlebird/launches/littlebird-2)
- Linear: [Introducing Linear Agent](https://linear.app/changelog/2026-03-24-introducing-linear-agent), [How we use Linear Agent](https://linear.app/blog/how-we-use-linear-agent-at-linear), [How we built Triage Intelligence](https://linear.app/blog/how-we-built-triage-intelligence), [Changelog](https://linear.app/changelog), [AI at Linear](https://linear.app/docs/ai-at-linear)
- Scape: [Stork listing](https://www.stork.ai/en/scape), [Product Hunt reviews](https://www.producthunt.com/products/scape-3/reviews), [Welcome.AI](https://welcome.ai/company/scape/technology)
- Email tools: [Zapier: Shortwave vs Superhuman](https://www.zapier.com/blog/shortwave-vs-superhuman), [Zapier: best AI email assistants](https://zapier.com/blog/best-ai-email-assistant/), [Missive: AI email assistants](https://missiveapp.com/blog/ai-email-assistant), [Superhuman's guide (vendor)](https://blog.superhuman.com/best-ai-email-assistant/)
