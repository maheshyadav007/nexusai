# Known problems

Problems found while testing on the real mailbox and model, and how we plan to solve each one. Remove a row once it's fixed and proven on the real account.

Last reviewed: 2026-11-04. See [implementation evidence and limits](EMAIL_AGENT_IMPLEMENTATION.md). Rows requiring real-account proof stay open.

## Security

| Problem | What happens | How we'll solve it |
|---|---|---|
| No login, and open to the network | For testing, any machine on a private network can open the app by IP and use everything, including mail and agents. Must be fixed before real use | Add a login and HTTPS, and listen only on this computer by default |
| Secrets are in a plain file | A missing keyring blocked opening a Home on Linux, so the Home's key and sign-ins now go in `secrets.json`, readable only by this user but not encrypted. Anything running as this user can read them, and the database is only as safe as this file | Once things are stable, go back to the OS credential store, with a clear fallback when none exists, and move these secrets across |
| Folder-watch limit on Linux | If Linux runs out of file watches, opening a Home may fail with an error. Not reproduced | Catch it, and carry on without watching for file changes |

## Other machines

The app has only ever been run for real on one Mac, so these come from reading the code and lockfiles. None were seen happening, except where noted.

| Problem | What happens | How we'll solve it |
|---|---|---|
| Windows acceptance is unverified | Checks have run on a Mac; a packaged Windows installation and real update cycle are not yet proven | Run the [Windows build/test pipeline](WINDOWS_RELEASE_GUIDE.md), then A → B → C updates and real mail checks on a company laptop; automate the proven checks later |
| Older systems can't install | `onnxruntime` has no build for Intel Macs or macOS before 14. `onnxruntime` and `sqlcipher3` need glibc 2.28 or newer on Linux, so RHEL or CentOS 7 and Ubuntu 18.04 fail. `cryptography` has no Windows on ARM build | Make meaning search an optional install, and check the system before setup |
| Company networks | Web requests trust a built-in certificate list, so a company that inspects traffic can break model sign-in and connectors. `next build` downloads fonts from Google, so a blocked network can fail the build | Use the system's certificates, and ship the fonts in the repo |
| Commands use the wrong shell | The agent is told the shell is `$SHELL`, but commands run in `zsh`, or `/bin/sh` if that's missing. On Ubuntu that's `dash`, so bash commands can fail | Run commands in the shell the agent is told about |
| Opening the app by IP address | Toasts and Copy now work over plain http. Browsers still don't grant notifications there | Add HTTPS |
| Memory limit on attachments | The attachment reader is capped at 2 GB of address space. Linux enforces this, and a Mac ignores it, so large files may fail only on Linux | Test on Linux, then raise the limit or change how it's measured |
| Moving a Home to another computer | The key stays behind in the app data folder or Keychain, so the Home asks for its recovery key, and model and connector sign-ins must be repeated | Explain this at setup, and make sure the recovery key was saved |
| Network and virtual drives | The check misses some types, such as `virtiofs`, `vboxsf`, `ceph` and WSL's `/mnt/c`, where the database can be slow or unreliable | Add them to the list, and warn on WSL mounts |
| Frontend and backend must share an account | The frontend reads the backend's token from the user's app data, and remembers it. A different user, or a reset, gives "Request refused" until it restarts | Read the token again after a refusal, and say what's wrong |
| Ports already in use | Other programs often use 4000, such as NoMachine, and the frontend's port is fixed | Add one setting for both ports, and a clear message when one is taken |
| No fixed Node version | Node 22 is only mentioned in the README | Add `engines` and `.nvmrc` |

## POP3 and company servers

The app has connected to the real company servers, and the first feedback came from there. Most of the automated tests still use fake servers.

| Problem | What happens | How we'll solve it |
|---|---|---|
| Everything starts unread | POP3 has no read marks, so all downloaded history shows as unread | Offer "mark older mail as read" after the first download |
| Nothing syncs between devices | Read marks, flags, archiving and folders stay on this computer, and mail reaches the server's other clients as they left it | Use IMAP if the company turns it on. POP3 can't do this |
| Sent mail exists only here | The server keeps no Sent folder for POP3, so mail sent from other programs doesn't appear, and a lost Home loses this copy | Import a PST for older sent mail, and rely on Home backups |
| New mail takes up to a minute | POP3 can't announce mail, so the mailbox is checked every minute | Lower `check_every_seconds` if a minute is too slow |
| Other mail clients can clash | Servers lock a POP3 mailbox while it's open, so Outlook may fail during a check, and we wait and retry if it's the other way round | Check on the real server, and lengthen the gap if it happens |
| A server without `UIDL` can't sync | We use it to tell which mail is new, and every modern server has it. Without it, the app keeps retrying | Say so plainly if it's ever seen |
| A company certificate fails | Certificates are checked by default, and a private one fails with a message naming the setting | Set `NEXUSAI_MAIL_VERIFY_CERT=false` for now, then add the company's certificate |
| Replies from the company model aren't checked yet | Tool calls and thinking written as text are now read in more forms, but this was tested with made-up replies, not the real models. Replies that still can't be read are logged as `model_reply_not_a_tool_call` | Check on the company server with the thinking and non-thinking models, and add any new form they use |
| First reply from some thinking models | If the server's template opens the thinking tag itself, nothing marks the start, so that model's first reply shows its thinking as words. Its later replies are right until the app restarts | Remember this per model across restarts, if it's seen on the company server |
| Stopping during a rate limit wait | A run waiting for a free slot can take up to a minute to stop | Check for a stop while waiting |
| Password in the clear | SMTP on port 25 without TLS sends the password unencrypted if the server asks for one | Use TLS once the servers allow it |
| API key in a plain file | `.env` holds the model key unencrypted, though it isn't committed or passed to the agent's commands | Move it with the other secrets to the OS credential store |
| A proxy can catch internal addresses | With `HTTP_PROXY` set, calls to the model server go through the proxy, and may fail | List the server in `NO_PROXY` for now, then bypass the proxy for private addresses |

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
| It ignores pending decisions | It can say "your plate is quiet" while 8 decisions wait on Today | Implemented: the brief now receives pending approvals, questions, mail suggestions and category proposals. Regression tested; confirm on the next real brief. |
| Learning only uses what's typed | It only learns from like, dislike and comments, and most days people give none | Implemented: actor/account/version-scoped opens, task outcomes, sends and explicit reactions are recorded. Read flags remain marked-read counts; ignored/inactive is not inferred dislike. Prompt preferences require approval. Validate usefulness with real user feedback. |
| Reactions apply to the whole brief | One bad line counts against all of it | Add a like and dislike for each item |
| Feedback isn't consolidated | It keeps only the last 10 reactions, so older requests drop off | Mail review can propose evidence-backed scoped instructions for explicit approval; approved instructions persist with expiry/version/restore. Recent brief reactions remain bounded. Measure consolidation on real usage; no automatic permanent rule from one rating. |

## Needs you

| Problem | What happens | How we'll solve it |
|---|---|---|
| Old suggestion text can disagree with the counts | One card says "File 712 emails" while its reason says "These 718", because the reason was written before the model was told to leave counts to the app | The new prompt prevents this. Replace the old suggestions at the next inbox review, or decline them |
| Task and reminder for one item | Quip has both, made before the fix | The person declines one. Nothing else to do unless it comes back |

## Agents list

| Problem | What happens | How we'll solve it |
|---|---|---|
| Inbox review says "Hasn't run yet" | Its first run happened inside the Mail agent's chat, so it isn't counted | Implemented: Inbox review uses its own turn origin and timestamp, including shared-chat runs. Regression tested; confirm after the next real review. |
| Removed agents can vanish | A removed agent is only listed if it left a chat behind | Keep a small record when an agent is removed |

## Mail handling

| Problem | What happens | How we'll solve it |
|---|---|---|
| Mail agent judges one conversation per call | Kept on purpose, since each email gets the agent's full attention. On the real account it used about 5,170 input tokens per email, so reading 400 costs about 2M | Shorten the repeated instructions if the cost becomes a problem |
| Overlapping categories in different words | HR and HR feedback are caught by their shared word, without a model. HR and People team need the Inbox review to fold them, which hasn't been seen on company mail | Check after the next review on company mail |
| Priority can only follow categories | A category can be shown in the Priority inbox, but a server folder can't | Add it for server folders if it's wanted on IMAP. POP3 has none |
| Reply-all on a broadcast | It still prefills everyone, which could be thousands of people | Warn above a set number of recipients, and suggest replying to the sender only |
| Older threads keep old categories | For example, a Suki confirmation is still in Promotions and an Adobe thread in Updates | Offer a one-time pass over the person's own conversations, with the token cost shown first |
| Hourly check starts off | A new Home treats the Mail agent as "both", but its hourly schedule stays off until the settings are saved, so no hourly check runs | Startup already enables the hourly schedule for the default mode; added a new-Home regression test. Confirm after creating a real Home. |
| Suggestions list is slow | It's the slowest query behind Today, at about 0.9 seconds | Cache the sender counts and refresh them when mail changes |

## Not yet proven on the real account

These pass with fake mail or a fake model, but haven't run for real. Each is finished once it has.

| What | How we'll prove it |
|---|---|
| Live mail through the new prompts | Watch the next real emails get judged, then check the results |
| A real sent mail flipping waiting and needs you, and the follow-up notice | Wait for the person's next real reply and follow-up date |
| Hourly check on the new prompt | Read its next run |
| A category suggested for the Priority inbox | On Gmail the Inbox review looked and found none worth it. Check on company mail, where more of it needs the person |
| `[PLM]`, `[Swarm]` and `[3GPP Briefing]` mail on the company server | Automated mail stays in its folder with no model call, and replies reach the agent. Check with real mail |
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


## Email audit follow-up

The 4 November reliability fixes and scoped prompt-feedback controls have deterministic regression coverage and synthetic browser verification; see [the implementation record](EMAIL_AGENT_IMPLEMENTATION.md). Real incoming/sent mail, company-provider tool parsing, real brief coverage and preference usefulness still need observation on the real account. No broad mailbox re-triage was used as a test.

Remaining limits: item-level brief ratings, observed draft-edit style learning, retention/pruning controls for the interaction ledger, full conflict adjudication, provider-specific quality/latency budgets, multilingual mail evaluation, and a Home-specific remembered-chat reset are not completed here. Sender scope currently matches an address present in supplied conversation context; it is not an authenticated current-sender identity policy. Whole-brief ratings do not validate every sentence.
