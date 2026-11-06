# Identity plan

The name, logo, personality and wording for the app and its chief of staff. Nothing here is built yet. "NexusAI" stays until a name is chosen.

Last reviewed: 2026-11-03.

## Status

| Part | Status |
|---|---|
| New words in the app | Agreed, to be changed later |
| Name | Not chosen. Needful is the current recommendation |
| Logo | Proposal |
| Agent personality | Proposal |

## Name

The name should be fun, and an ordinary word with some personality, like recent YC names such as Gravy, Hedge, Juno and Smol Machines. Plain English only, with no Hindi or Sanskrit. It has to be easy for Indians to say and relate to, and can't suggest mail alone.

| Name | Why | Catch |
|---|---|---|
| **Needful** (recommended) | From "please do the needful", which every Indian office knows. It's funny, it's the agent's whole job, and the app's main button can say "Do the needful" | Could read as a joke about Indian English outside India, and a serious buyer may not take it seriously |
| **Prepone** | Indian English for moving something earlier, and the agent gets to things before you ask | Means nothing to many people abroad, and it's harder to turn into a personality |
| **Nightshift** | It works while you sleep and hands over in the morning, and Indian IT people know night shifts well | [NightShift AGI](https://www.vcbacked.co/company/nightshift-agi) is a similar name, and it undersells daytime work |

Ruled out:

| Name | Why |
|---|---|
| Sorted | [Sorted AI](https://www.cbinsights.com/company/sorted-ai/people) is already a personal assistant from Delhi |
| Tiffin | [TIFIN](https://www.capterra.com/p/10050254/TIFIN-AI/) is a well-funded AI company with almost the same name |
| ChiefOS, OfficeLab, ChiefLab, ChiefDesk, DeskLab, WorkCabin, LocalStudio, DayLab | Accurate, but not fun |
| Marshal, Keystone, Compass | Not fun, and too serious |
| Righthand | Already an [AI employee product](https://www.gappsy.com/tools/righthand/) in this category |
| Mantri, Birbal, Sanjaya, Munshi, Vidur, Saarthi, Tenali, Wazir | Hindi or Sanskrit, or from Indian history and epics |
| Attaché | Hard to say and relate to in India |

Before choosing: these names only had quick web searches. Get a proper trademark search done, and check whether Samsung has a say in naming or ownership before any wider rollout.

## New words in the app

| Now | Becomes | Where |
|---|---|---|
| Needs you | For your decision | `today.needsYou`, and other strings that use the phrase |
| Allow | Approve | `approvals.allowCount`, and the other approval buttons |
| Morning brief | Your brief | `today.prep`, the schedule title, the Agents list and Settings |
| Know you better | First meeting | `setup.interview.label`, `INTERVIEW_TITLE` in `triggers.py`, `registry.py`, and a migration for existing chats |

Search the strings and tests for each word when changing it, since browser tests find buttons by their text.

## Logo (proposal)

An envelope with its flap showing, and one terracotta dot for the one thing that needs you today. The mark should be redrawn around the chosen name's first letter.

- Stays clear at 16px and in one colour.
- Uses the existing terracotta and warm paper, with the name in the serif display font.
- The dot pulses while the agent works, and can replace the brain icon.
- The AI glow appears only while it's working, so the logo itself stays flat.
- No sparkles, robots, brains, briefcases or gradients in the logo.

## Agent personality (proposal)

**Who it is:** your chief of staff, on your own machine.

**Habits:**
- Leads with the one thing that matters.
- Recommends rather than asks open questions.
- Gives its reason.
- Says when it's unsure.
- Never acts on your behalf without your approval.

**How it sounds:** brief and calm, for example "Priya has waited three days. I drafted a reply for you to check." No exclamation marks, and no "Happy to help!".

**Its staff:** the Mail agent, Inbox review and the others work for it. People deal with the chief of staff, and the specialists appear only in the Agents list.

## Order of work

1. Choose the name and clear its trademark.
2. Draw the logo, with variations in light and dark, and compare them at real sizes.
3. Change the words in the app.
4. Put the personality into the system prompts, and check it with `make eval-mail`.
5. Rename the app in one pass: UI, docs, repo, and Home folder paths, with a migration for existing Homes.
