# Mail organization

What we intend to build for sorting mail, marking what matters, and learning about the person, and the order to build it in. Decided 2026-11-06. Not built yet.

## Why

Testing on real mail showed four problems:

- **Overlapping folders.** The agent names folders one email at a time, so HR, HR team and HR notification appear side by side. The name check (`category_names.py`) only joins names that share a word, and it runs only in the agent's own paths.
- **Duplicate tasks and reminders.** A task counts as a repeat only with the exact same title in the same conversation (`planner.has_task`). The same request sent again, or worded differently, makes a second one, and a declined task can come back.
- **Expensive, slow learning.** Onboarding sends up to 400 past emails to the model one at a time (`mail_agent.queue_learning`), about 2M input tokens, and runs only once, not after a PST import.
- **Not using history.** Past judgements and the person's corrections are kept, but rarely brought back when the next email is judged.

## Goals

1. Most mail is filed by fixed rules with no model call. The model is kept for mail that needs judgement.
2. Every folder works the same way. Folders differ only in their settings and defaults.
3. The person decides which folders exist. The agent only suggests.
4. Importance is marked on every conversation, including past mail, without judging every past email one by one.
5. Learning happens in a few batched calls, the same way for onboarding, a PST import or any large download.
6. Archive and delete can always be undone, back to exactly the previous state.
7. Each step can be measured on the real Gmail account.

Not in scope here: agents passing messages to each other, and linking tasks and reminders across emails. See Later.

## Main ideas

- **Every folder is a view.** Filing mail doesn't move it. A folder is a filter on the conversations table (`category` and `extra_categories` in `modules/mail/store.py`), as it is today. Server folders on IMAP are the one exception.
- **Rules first, then the model.** A fixed rule that matches files the mail with no model call. Only what no rule catches is judged.
- **Exact or Smart.** Every folder is one or the other:
  - **Exact:** matches the sender or the subject exactly. Never reaches the model.
  - **Smart:** described in the person's own words. The model decides what belongs.
- **Learn from groups, not single emails.** Past mail is grouped by sender and subject, and the model reads the groups.

## Views

| View | Shows |
|---|---|
| **Priority** | The main inbox, like Gmail's Primary. See the Priority rule below |
| **Important** | Mail the model or the person marked important, and mail waiting on the person (`status = 'waiting_on_you'`) |
| **All mail** | Everything |
| **A folder** | Mail in that folder |

Starred stays as it is, and only the person sets it.

## Folder settings

| Setting | Values |
|---|---|
| Mode | Exact or Smart |
| Rule | Exact only: sender, or subject starting with a prefix such as `[PLM]` |
| Description | Smart only: one or two lines, like "NexusAI: my project, the desktop app, mail from the release team" |
| Show in Priority | On or off. Right-click a folder to change it |

Switching a folder's mode:

- **Exact to Smart:** the description is prefilled from the rule and the folder's top senders, for the person to edit. New mail starts going to the model. Sorting older mail again is a separate button that shows the token cost first.
- **Smart to Exact:** the rule is prefilled from the senders the model filed there most. Mail already in the folder stays.

## Default folders

| Folder | Comes from | Mode | Show in Priority | Reaches the model |
|---|---|---|---|---|
| PLM, Swarm, 3GPP Briefing | Starter rules, subject starts with the prefix | Exact | Off | No |
| Updates | Header rules: system notices, generated mail, no-reply senders, company bulk mail | Exact | Off | Only when the subject looks important (see Header rules) |
| Promotions | Header rules: bulk or marketing mail from outside the company | Exact | Off | No |
| Forums | Header rules: mailing lists | Exact | Off | No |
| Social | Header rules: social networks, personal accounts only | Exact | Off | No |
| Broadcast | Built in: mail to many people that no rule above caught | Smart | Off | Yes |
| Folders the person makes | The person | Smart | On | Yes |

A folder with no mail is hidden from the sidebar. Broadcast is the only new default folder. Important broadcasts, like a mandatory performance review, reach Priority because they're marked Important.

## How a new email is handled

1. **The person's own rules**, then the starter rules, then the header rules. First match wins.
2. **An Exact match is filed with no model call.** "Starts with" is literal: `[PLM] Build 12` matches the PLM rule, and `Re: [PLM] Build 12` doesn't. Today `Re:` and `Fwd:` are stripped before the check (`_condition_matches` in `modules/mail/rules.py`); that stops, and the starter rules lose `read_replies`. If two Exact rules match, the first in sidebar order (`position`) is the main folder and the other is added as an extra.
3. **Everything else is judged in one model call,** which answers:
   - Is it important, and is it waiting on the person?
   - Which Smart folders does it belong to? It can be none, or more than one. Exact folders take the main place, and Smart folders are added as extras.
   - Later: is it part of something already open?
4. **The model never makes folders.** It can suggest one, and the person decides.
5. **The person's choice wins.** Mail they filed by hand, and marks they set, stay as they are.

The description of every Smart folder goes into that one call, so Smart folders add no model call. Each description adds to the cost of every email, so they stay short.

### Header rules

The header rules in `modules/mail/rules.py` don't change. They include one exception to "Exact never reaches the model": generated and no-reply mail filed in Updates still goes to the model when its subject matches `WORTH_A_LOOK` (security, password, payment, deadline and the like). These are guesses from headers, not the person's rules, and a suspicious sign-in alert must not go unjudged. Promotions keeps today's behaviour and never reaches the model.

## The Priority rule

A conversation in the inbox shows in Priority if any of these is true:

- It's Important, or waiting on the person.
- One of its folders has Show in Priority on.
- It's in no folder.
- Its latest message matched no Exact rule.

It's hidden only when every folder it's in has Show in Priority off, its latest message was filed by one of their rules, and it isn't Important.

| Conversation | Folders | In Priority? |
|---|---|---|
| `[PLM] Build 12 passed` | PLM (off) | No |
| `Re: [PLM] Build 12 failing`, from a colleague | PLM (off) | Yes, latest message matched no rule. Judged by the model |
| Then `[PLM] Build 13 passed` arrives in it | PLM (off) | No, unless it was marked Important |
| Company announcement | Broadcast (off) | No |
| Mandatory performance review, to all | Broadcast (off), Important | Yes |
| NexusAI release, to all | Broadcast (off), NexusAI (on) | Yes |
| A colleague writes to them | None | Yes |

## Learning from bulk mail

The same procedure runs whenever a lot of mail arrives at once:

- the first download, during onboarding
- a PST import
- Read more past mail
- any download that adds more than 50 messages at once

Mail is first filed by the rules, as usual, so Priority works straight away. Then:

| Stage | What happens | Model calls | The person sees |
|---|---|---|---|
| 1. Group | Mail no rule filed is grouped by sender and subject, with `Re:`, `Fwd:`, dates and numbers removed. Counts for each group: how many, whether the person replied, whether they're in To, whether it's bulk | None | Progress |
| 2. Learn | Groups go to the model, about 30 a call. For each group: a note on who it is and what they send, a usual importance, and a suggested folder if it belongs in one (name, Exact or Smart, description, and which other groups belong with it). Also notes about the person: who matters, and their projects and systems | A few, batched | Progress |
| 3. Ask | The first-meeting interview asks only what the notes are unsure of, a few questions at most, and shows the suggested folders with the app's own counts, like "HR: 3 senders, 42 emails, Smart". Overlapping suggestions are shown as one. Accepting creates the folder. It can be skipped, and then the best guesses are used | One conversation | Questions and suggested folders |
| 4. Mark | Each conversation gets its group's usual importance, as changed by the answers, raised to high when the app's own signals say so: an unanswered message to the person, a `WORTH_A_LOOK` subject, a deadline date in the text, or they're in To from someone they often reply to. Accepted folders file their mail | None | Importance on past mail |
| 5. Judge recent mail | Conversations from the last 7 days that no rule filed are judged one by one, with the notes and answers in hand, newest first and at most 200. Only these get a status, tasks, reminders and drafts | One for each | Important, waiting on them, tasks and drafts |
| 6. May be missed | Older conversations from the last 30 days with an unanswered message to the person become one card on Today: "12 older conversations may still need a reply". The person picks. No tasks are made from older mail on its own | None | One card |

The interview comes before marking because the person's answers change the marks.

A group seen before needs no model call. A later import learns only the new groups, and the interview comes back only when the notes are unsure of something new.

| Conversation | Group's usual importance | Signal | Marked |
|---|---|---|---|
| HRMS: "Payslip for October" | Low | None | Low |
| HRMS: "Form 16 pending, last date 20 Nov" | Low | Deadline words and a date | High |
| Priya: "Can you review the spec?", never answered | Normal | Unanswered, to them | High |
| A tech newsletter | Low | None | Low |

Notes from stage 2 go where the agent's learned notes go today (`agents/mail/learned.md`, shown in Prompts and memory). Notes from mail stay marked as guesses until the person confirms them.

## Archive and delete

Archive and delete move a conversation and change nothing else: its folders, importance, status, follow-up date, tasks and reminders stay as they were. Restoring it puts it back in the inbox in exactly that state, so it shows again in Priority, Important and its folders.

| Today | Needed |
|---|---|
| Archive and Delete on a conversation (`ThreadScreen.tsx`), with no Restore | Restore from Archive and Trash, and Undo straight after either |
| `thread.move` only moves messages that are in the inbox (`modules/mail/module.py`), so moving back is ignored | Moving back from archive and trash to the inbox |
| Conversation state is kept on `threads`, and a move doesn't touch it | Keep it that way, with a test that restoring brings back every field |

Deleting on the server still follows the never-delete setting. A refused delete stays on this computer, and restoring it needs nothing from the server.

## What changes in the code

| Change | Where |
|---|---|
| `mode` and `description` on folders. Show in Priority uses the existing `in_priority` | A migration in `modules/mail/store.py` |
| New Priority and Important filters | `FOLDER_FILTERS` in `modules/mail/store.py` |
| The rule that filed each conversation's newest message, kept on the conversation | `refresh_thread` in `modules/mail/store.py` |
| "Starts with" checks the subject as written, and starter rules lose `read_replies` | `modules/mail/rules.py`, `_add_starter_categories` in `modules/mail/module.py` |
| Broadcast as a built-in Smart folder | Created once for each Home, like the starter folders |
| The judgement returns importance and a list of Smart folders, checked against the real ones | `record_triage` in `modules/agent/tools.py`, `mail_agent._apply` |
| The model can't create folders | Replaces `_note_category` and the 12-folder limit in `mail_agent.py` |
| Restore and Undo | `thread.move` in `modules/mail/module.py`, `ThreadScreen.tsx` |
| Learning by group | Replaces one-by-one learning in `mail_agent.queue_learning`; reuses `signals.sender_table` |

The new Priority filter, as a sketch:

```sql
in_inbox = 1 AND (
  importance = 'high' OR status = 'waiting_on_you'
  OR (category IS NULL AND extra_categories = '[]')
  OR category IN (SELECT name FROM mail_categories WHERE in_priority = 1)
  OR EXISTS (SELECT 1 FROM json_each(extra_categories)
             WHERE value IN (SELECT name FROM mail_categories WHERE in_priority = 1))
  OR latest_rule IS NULL
)
```

The current rule that shows recent unjudged mail goes away, since mail no rule filed now always shows.

### Existing Homes

| Today | Becomes |
|---|---|
| Starter folders, and folders with a sender or subject rule | Exact |
| Updates, Promotions, Forums and Social | Exact, Show in Priority off |
| Folders the agent or the person made with no rule | Smart. Until a description is written, the name is the description |
| Overlapping folders the agent made, like HR and HR team | A card on Today offering to merge them, for the person to decide |

## Build order

1. Folder settings and defaults, with the migration of existing folders.
2. The new Priority and Important views.
3. Exact rules checked as written, and filing before any model call.
4. Smart folders in the judgement, and the model no longer creating folders.
5. The mode switch in Settings, on right-click and in chat.
6. The merge card for overlapping folders.
7. Restore and Undo for archive and delete.
8. Learning by group, for onboarding and every bulk import.

Each step is checked on the real Gmail account before the next one starts.

## How we'll know it works

Measured on the real Gmail account:

| Measure | Why |
|---|---|
| Share of mail filed with no model call | Cost, and goal 1 |
| Model calls and tokens for onboarding | Compared with about 2M tokens today |
| Folders the person renames or merges | Fewer means better suggestions |
| Important mail the person unmarks, and mail they mark that wasn't | How good importance is |
| Restores that bring back every field | Must be all of them |

## Later

- **Linked work:** one open item for each real request, with repeats linked to it, so the same reminder sent again doesn't make a second task. Tasks and reminders closing when the conversation they came from is resolved.
- **A company pack:** known broadcast lists, systems and folders for an organization, kept as a data file outside the code, so a new person starts with them.
- **Agents working together:** shared records rather than messages between agents.

## Still to decide

- Header rules run first, so Broadcast only gets mail to many people with no list or bulk headers. Check on real mail whether important broadcasts end up in Forums or Updates unjudged.
- Which signals raise a past conversation to high in stage 4, and how far. Tune them on the real account before relying on them.
