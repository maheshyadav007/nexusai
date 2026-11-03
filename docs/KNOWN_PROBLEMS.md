# Known problems

Problems found while testing on the real mailbox and model, and how we plan to solve each one. Remove a row once it's fixed and proven on the real account.

Last reviewed: 2026-11-03, at commit `8a5dafe`.

## Search

| Problem | What happens | How we'll solve it |
|---|---|---|
| Promotions can outrank real mail | `flight booking` puts marketing above the real Air India check-in email, because those promotions match the words better | Rank transactional mail (booking, receipt, confirmation) above marketing, using the headers and categories we already have |
| Duplicate documents | The same résumé is listed once for each email it was attached to | Group search results by the file's hash, show one row, and list the emails it came from |
| Password-protected attachments | 80 attachments can't be searched inside | Let the person enter a password once per sender and read them locally, without saving the password in plain text |
| Image attachments and scans | 50 attachments have no text, including the passport scan, so only their names can be found | Add local OCR, which was deliberately deferred |
| First search after a restart is slow | It takes about 7 seconds because the meaning model loads on first use | Load the model in the background when the app starts |
| Meaning search misses long questions | Long, sentence-like queries rarely stand out from unrelated mail. The agent now gets the closest matches, marked as possibly unrelated, and is told to use a few words | Measure this on real queries and tune the threshold. Re-run the agent, since this fix hasn't been tried with the real model |
| Agent search is expensive | Four questions used about 450K input tokens, roughly 70K to 160K each, because every step resends the conversation and full threads | Return shorter results, stop reading the work board on every turn, and trim old tool results from the conversation |

## Morning brief

| Problem | What happens | How we'll solve it |
|---|---|---|
| It ignores pending decisions | It can say "your plate is quiet" while 8 decisions wait on Today | Add approvals, questions and suggestions to what the brief is given |
| Learning only uses what's typed | It only learns from like, dislike and comments, and most days people give none | Add implicit signals: which items were opened, finished or ignored |
| Reactions apply to the whole brief | One bad line counts against all of it | Add a like and dislike for each item |
| Feedback isn't consolidated | It keeps only the last 10 reactions, so older requests drop off | Summarize feedback weekly into a short "how I like my brief" note the person can edit |

## Needs you

| Problem | What happens | How we'll solve it |
|---|---|---|
| Old suggestion text can disagree with the counts | One card says "File 712 emails" while its reason says "These 718", because the reason was written before the model was told to leave counts to the app | The new prompt prevents this. Replace the old suggestions at the next inbox review, or decline them |
| Task and reminder for one item | Quip has both, made before the fix | The person declines one. Nothing else to do unless it comes back |

## Agents list

| Problem | What happens | How we'll solve it |
|---|---|---|
| Inbox review says "Hasn't run yet" | Its first run happened inside the Mail agent's chat, so it isn't counted | Record each run against the agent that made it, not just its chat |
| Removed agents can vanish | A removed agent is only listed if it left a chat behind | Keep a small record when an agent is removed |

## Mail handling

| Problem | What happens | How we'll solve it |
|---|---|---|
| Reply-all on a broadcast | It still prefills everyone, which could be thousands of people | Warn above a set number of recipients, and suggest replying to the sender only |
| Older threads keep old categories | For example, a Suki confirmation is still in Promotions and an Adobe thread in Updates | Offer a one-time pass over the person's own conversations, with the token cost shown first |
| Suggestions list is slow | It's the slowest query behind Today, at about 0.9 seconds | Cache the sender counts and refresh them when mail changes |

## Not yet proven on the real account

These pass with fake mail or a fake model, but haven't run for real. Each is finished once it has.

| What | How we'll prove it |
|---|---|
| Live mail through the new prompts | Watch the next real emails get judged, then check the results |
| A real sent mail flipping waiting and needs you, and the follow-up notice | Wait for the person's next real reply and follow-up date |
| Hourly check on the new prompt | Read its next run |
| Accepting a suggestion, including archiving on Gmail | The person accepts one, then we check the result on Gmail |
| `read_recipients` with the real model | Judge a real broadcast with the mail eval |
| Saving the Know you better answers | The person clicks Allow 3 on Today, then we check the prompts and the next judgements |
| Like, dislike and comments reaching the next brief | The person reacts to a brief, then we read the next one |
| Opening a search result with the results beside it | Open a result that's already been read, since opening unread mail marks it read on Gmail |
| A notice with an email open | Open a read email, fire a test reminder and measure its position |
| The whole app on Windows | Run it on a Windows machine |

## Test gaps

| Problem | What happens | How we'll solve it |
|---|---|---|
| Reminder test doesn't fire in the browser tests | Reminders never fired in that environment, and we didn't find out why. Notice position is checked with a question from an agent, and was measured once with real reminders | Find out why, then add a real reminder test |
| Mail eval is only a smoke test | The prompts were tuned on the same 27 emails, so 26 of 27 overstates quality | Add cases the prompts weren't tuned on, ideally reviewed real threads |
