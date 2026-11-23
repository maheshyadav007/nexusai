# Flow fixes: one AI gate, a true timeline, a sidebar you understand at a glance

Status, 2026-11-23 (night): **Phases 0–4 built** on branch `conversations`, mockup boards 13–17 approved. Phase 5 (Today cleanup) is not built and needs its own mockup.

**What was built**
- **0.1** Mail comes down 50 at a time.
- **1.1** No exceptions: `decision_for` keeps all of a kept rule's mail from the AI; `_names_them`, `look_closer`, `Decision.exception`, `Stored.worth_a_look` and `_deserves_a_look` are gone; Sort rules no longer write `mentions`/`read_replies` (old rules keep the fields, which nothing reads). Sorting files all of a kept sender's mail, the conversations it was in too (no more `spoken`); the sender report has no `reach`/`through` and `SortEmail` no `names_you`. The app's Sort page, Rules settings, Today's sort card and the sort lab (`sortlab/lab.py`, `page.html`) no longer say anything "still reaches the AI".
- **One test:** `store.hidden_from_ai(column)`, the folder is in `KEPT_FOLDERS`, used everywhere below.
- **1.2** `mail_agent.next_turn` checks the folder again and settles hidden conversations as skipped.
- **1.3** Learning (`bulk_learning` queue, finalize, review candidates, unseen count) and `unjudged_count` leave hidden conversations out; learning no longer queues kept mail with a worrying subject.
- **1.4 (D3)** Code no longer joins kept mail to matters (`they_answered`); `matters.link` refuses hidden conversations; the AI's matter context leaves them out.
- **1.5 (D2)** Chat tools `search_mail`, `read_thread`, `list_mail`: an agent running by itself never gets hidden mail; when the person asks, it's shown and labelled "kept from the AI; shown only because the person asked" (`signals.asked_by_person`, `signals.hidden_threads`). The brief's mail list leaves hidden conversations out.
- **1.6 (D6)** `conversations.follow_folders`, run on `mail.changed`, `rules.changed`, `categories.changed` and `thread.updated`: a conversation filed where the AI doesn't read has its open tasks, reminders and deadlines closed; moved back, they open again (unless it was marked done meanwhile). Hidden conversations drop out of matters (`_threads_of`), Priority and Important (unless their folder is marked Show in Priority), the brief and the day's matter changes. Undo is moving it back; there's no toast yet (Phase 4 adds one for "Hide from AI").
- **1.7** Not stored: with one gate, "did the AI read it" is "is its folder hidden", and the reason is the email's `rule`. Phase 3's chip reads those.
- **Phase 2** `matters._story`: the timeline is the emails in date order (read from the mail, not stored entries), the earliest one "started", the first email of each conversation that joined later "linked" with its reason (when the starter isn't the earliest, the earliest's reason is used), and actions at their real time. Paging, the matter's started date and the AI's "lately" use the same story.
- **Tests:** rule engine, sorting, sort lab, organization, matters and conversations updated; new tests for the folder re-check, learning, follow-folders with its way back, and the older-half-joins-later timeline.

**Phases 3 and 4, as built (boards 13–17)**
- **Names:** the homes are Read by AI and Hidden from AI everywhere (sidebar, Sort page, menus, New/Edit folder, empty states, the rule engine's "why", agent tool notes; `folders.INBOX`/`KEPT`). The old names stay reserved so no folder takes them.
- **Sidebar** (`ui/shell/HomeNav.tsx`): an open eye (`readByAi`) or closed eye (`keptFromAi`) on each home and on every hidden folder; both homes fold (`useRememberedFold`), Hidden from AI starts folded; a size bar beside each top folder (`Progress`, quiet on the hidden side); Calendar has a fixed row under Hidden from AI; the folders shown are those ticked on the Sort page (`useShownFolders`, kept with the sidebar layout as `folders:reads`/`folders:kept`), or the biggest 3 until anything is ticked.
- **Sort page** (`ui/features/mail/SortScreen.tsx`): a flow strip (mail in → rules → Read by AI | Hidden from AI → folders → Priority) with live counts; on each side "In the sidebar: the biggest [− K +]", which also gives that many of the biggest senders a folder of their own, on both sides (a first sort starts the AI's side with up to 3 too); each folder has a tick, and unticked folders sit below, greyed, under "More folders"; clicking a folder opens a window with Emails, Senders (move them from there) and Rule tabs, the Rule button opens it on Rule; the page itself never expands. Ticks are saved with Save.
- **Email rows** (`ThreadRowView.tsx`): the side's eye and one chip, "Hidden: …", "rule: …", "AI: …", with the full reason on hover.
- **Hide from AI** (`modules/mail/hiding.py`, commands `mail.hide`, `mail.hide.undo`, query `mail.hide.preview`; `ui/features/mail/HideFromAi.tsx`): from the email menu, the matter page and each Week lane; asks "everything from {sender}" or "just this conversation", says what will happen, moves the mail (sender: its own kept folder or a new one named after it, with its rule; conversation: Automated), and one Undo puts back the rules, each email's rule, each conversation's folder, mail that came meanwhile, and removes a folder it made. Open work closes and the matter drops through `follow_folders`, and comes back on Undo. Hidden mail offers "Let the AI read" instead.
- **Timeline:** "Jump to start" loads every earlier page and scrolls to the top.
- **Sort lab** (`sortlab/page.html`): same names, a flow line with counts, and "A folder of their own for the biggest [− K +]" on the hidden side (the lab's result file has no folders for the AI's side, so K there stays the app's).

**Decided (2026-11-23): security alerts stay hidden.** A security alert (e.g. Google's "Security alert for …" from a no-reply address) is filed by the header rules into Kept from the AI and is not judged by the AI or shown in Priority, like everything else there. Before, it was the one deliberate exception (`docs/MAIL_ORGANIZATION.md`).

**Mockup:** boards 13–17 on the canvas (https://claude.ai/artifact/KXaVo81GjS2W1jT4cibnZU, under "Flow fixes"), approved and built.

> **The idea.** The folder tree is in (see `docs/FOLDERS_PLAN.md`), but the app still doesn't flow: the AI reads mail the sidebar says it doesn't, a matter's timeline tells its story out of order, the AI side starts empty, and the words and pictures need explaining. This plan makes three things true: **the folder is the AI's gate**, **every timeline is in date order**, and **a new person understands the sidebar without reading a sentence**.

---

## 0. Picking this up in a new session

1. Read this whole file, then `docs/FOLDERS_PLAN.md` (the tree, homes, filing order) and the "Object model" section of `docs/MATTERS_PLAN.md`.
2. Memory rules that apply (`~/.claude/projects/-Users-maheshyadav-Projects-nexusai/memory/MEMORY.md`):
   - **Plan stage: no building** until the person says build.
   - **Mockup before any UI change**, then wait for approval.
   - **Mail is the product.** Check on the real Gmail instance (:4000), not only tests.
   - **Never delete on Google's server.**
   - **No real-model evals without asking.** The fake model in tests is free.
   - **Throwaway Homes share the Keychain.** Set `NEXUSAI_SECRETS_TEST_FILE` on any scratch server.
   - **Complete features.** The natural next step happens by itself, no loose ends.
   - **Keep it simple.** One phase at a time; each passes its check before the next.
3. The person found these on the **internal (company) instance**, which can't be reached from here. Where the cause on internal matters, ask them to run the read-only query in task 1.0 and paste the result.
4. Task 0.1 is done (uncommitted). Everything else in this file is not built.

---

## 1. What the person saw (2026-11-23), and why

| # | Seen | Cause (in code) | Fixed by |
|---|---|---|---|
| 1 | Mail should come down 50 at a time | `initial_batch` 200, `backfill_batch` 100, `fetch_batch` 100 | Task 0.1 (done) |
| 2 | The AI side of the Sort page says "No folder" | "Give the biggest [N] their own folder" only works on the Kept side (`biggest` in `ui/features/mail/SortScreen.tsx`, `TOP_CATEGORIES` in `modules/mail/sort_view.py`). The AI side shows only folders the AI suggested, and on internal there were none | Phase 3 (D4) |
| 3 | The screen needs explaining; it should be understood by looking | Meaning is carried by sentences ("about" lines, card notes), not by icon, colour or shape. Folders in both homes use the same icons | Phase 3 mockup |
| 4 | "Inbox" and "Kept from the AI" confuse a new person; K can't be typed | "Inbox" means "everything" in Gmail. K is a fixed dropdown `[0, 3, 5, 10, 20]` (`BIGGEST` in `SortScreen.tsx`) | Phase 3 (D1) |
| 5 | Can't fold Inbox or Kept from the AI; Kept needs its own icon | Only folders inside a home fold (`HomeNav.tsx`); the homes don't. Folder rows in both homes use `folderRule`/`folderSmart`, so only a tint tells the sides apart | Phase 3 |
| 6 | No way to say "not this group, AI" from Week or Matters | No such action. Matter "Done" (`matters.done`) only closes the matter. "Add to folder" (`thread.move`) moves one conversation but makes no rule and leaves its suggestions, tasks and matter open | Phase 4 |
| 7 | Matter timeline reads "linked, linked, started" | Each "started"/"linked" entry is dated with its conversation's **newest** email (`link` in `modules/agent/matters.py`, `time=time or message["date"]`), not with when it began. The agent reads new mail before old (`ORDER BY event LIKE 'learn-%'` in `mail_agent.py`), so a matter often starts from the newer half and the older half joins later with an older date. The AI's matter context ("lately", `context_for`) uses the same times, so the AI gets the same muddled order | Phase 2 |
| 8 | "Almost there, but details and flow are missing" | See section 2 | All phases |
| 9 | The mail agent reads mail kept from the AI | See below | Phase 1 |
| 10 | Calendar is nowhere to be seen | Since `f030340` Calendar is an ordinary folder in Kept from the AI. It lost its calendar icon and fixed place, and competes on size for the top 3, so it usually sits under "Show all". It also only exists once the Sort page has been saved and found invitations | Phase 3 |

**Why the AI reads kept mail (9).** The sidebar and the agent decide "kept" differently. The sidebar asks *which folder is the conversation in now* (`KEPT_FOLDERS` in `modules/mail/store.py`). The agent was told once, *when the email arrived*, by the rules of that moment. So kept mail reaches the AI in four ways:

1. **Exceptions in the rule engine** (`decision_for` in `modules/mail/rules.py`): a keep rule still lets mail through if it "names you" (`_names_them`), is a reply (`read_replies`), or a header-guessed kind has a worrying subject (`look_closer` + `WORTH_A_LOOK`). "Names you" matches the person's full name or login (`mahesh.y`) anywhere in the text, which company tools write in almost every notice ("Assignee: …", "… commented"). Most likely the main cause on internal.
2. **Moved into Kept later**: mail queued or judged before it was filed into Kept, or moved there by hand, stays in the agent's queue. Nothing checks the folder again at judging time (`task_for` in `mail_agent.py`).
3. **Learning past mail** (`_conversations` in `modules/agent/bulk_learning.py`, `NOT_FROM_RULES` in `mail_agent.py`) treats "no rule stamped on the email" as "the AI may read it", which isn't the same as "not in Kept". Learning also queues recent "Automatically generated" mail with a worrying subject for judging.
4. **Code joins kept mail to matters** (`matters.link(..., start=False)` in `modules/agent/module.py`, `they_answered`). That's code, not the model, but the matter's context then goes to the AI.

Not checked yet: whether the chat's mail tools (`modules/agent/tools.py`) and the morning brief (`modules/agent/briefs.py`) read kept mail. Neither filters on `KEPT_FOLDERS` today (D2).

---

## 2. What's missing in the flow (8)

1. **Two meanings of "the AI reads it."** The root of the most confusing behaviour (9).
2. **Changes don't follow through.** Moving mail, finishing a matter and hiding a sender each do half the job; the rest is left for the person.
3. **You can act only on the Sort page.** Not where you see the problem: Week, Matters, an email (6).
4. **No visible "why."** An email doesn't say why it's in its folder or whether the AI read it. The exception that let it through isn't even stored.
5. **The timeline is a log of actions, not the story of the emails** (7).
6. **The AI side starts empty without the model** (2).
7. **Today still shows system status** (FOLDERS_PLAN Phase 6, not built).

---

## 3. Decisions (accepted)

All seven were accepted as recommended on 2026-11-23.

| # | Question | Recommendation | Why it matters |
|---|---|---|---|
| D1 | What do the two homes say? | **Read by AI** and **Hidden from AI**, the same words on the sidebar, Sort page, menus and dialogs. Routes stay `/mail/inbox` and `/mail/kept` | "Inbox" means "everything" in Gmail; a new person should know what a home does from its name alone |
| D2 | Chat and the brief: may they read Hidden from AI mail? | Agents that run by themselves (mail agent, learning, matters, brief) **never**. Chat only when the person asks for it, and the answer says it's from Hidden from AI | The gate has to be true for what runs unasked; the person asking is their own choice |
| D3 | Should code still join hidden mail to matters (e.g. a review tool's "approved")? | **No.** The folder is the gate for everything AI-facing; matters are AI-facing | One rule with no exceptions is easy to predict and to test |
| D4 | AI side without the model: what are the K default folders? | Same control as the Kept side: the **K biggest senders the AI reads** become folders, names editable; the AI's topic suggestions are added beside them when there are any | Gives both sides the same shape on day one, with no model needed |
| D5 | "Hide from AI" from a matter, week item or email: what does it cover? | Ask once: **everything from this sender** (default) or **just this conversation** | Sender is what people usually mean; one conversation is the safe choice for a person who writes about many things |
| D6 | Mail already judged that is now hidden: clean up? | Decline its **open** suggestions and tasks, close its open matters (each with Undo); keep the history | Hidden should mean gone from the AI's work, not only from its future |
| D7 | Timeline: open at the top (start) or the bottom (latest)? | **Bottom**, as today, with a one-click "Jump to start" | The latest is what you usually want; the start is one click away |

---

## 4. Phases and tasks

Each task: what, why, where, done when.

### Phase 0: Done

- **0.1 Mail comes down 50 at a time.** `initial_batch`, `backfill_batch`, `fetch_batch` = 50 in `kernel/defaults.toml`. Mail-sync tests pass (126). *Still to check:* with batches of 50 and `bulk_mail_threshold` = 50 (agent section of `defaults.toml`), a big download is still recognised as bulk. `_fetch_new` decides bulk from the total, so it should be; confirm on Gmail with a laptop-closed catch-up.

### Phase 1: The folder is the AI's gate (backend; needs D2, D3, D6)

**Purpose:** one rule, true everywhere: *mail in a folder the AI doesn't read never reaches the AI.*

- **1.0 Find the cause on internal.** Ask the person to run this read-only query with `sqlite3 "<Home>/system/nexusai.db"` and paste the result:
  ```sql
  WITH kept AS (SELECT name FROM mail_categories WHERE ai_reads = 0 UNION SELECT 'Automated' UNION SELECT 'Calendar')
  SELECT CASE
           WHEN m.rule IS NULL AND t.category_source = 'user' THEN 'A: moved to Kept by hand'
           WHEN m.rule IS NULL THEN 'B: no rule when it arrived, filed to Kept later'
           ELSE 'C: a keep rule matched, an exception let it through'
         END AS path, COUNT(*) AS emails, COUNT(DISTINCT m.from_addr) AS senders
  FROM triage_runs r JOIN messages m ON m.id = r.message JOIN threads t ON t.id = r.thread
  WHERE t.category IN (SELECT name FROM kept) GROUP BY path ORDER BY emails DESC;
  ```
  *Why:* confirms which of the four paths matters most before changing them.
- **1.1 No exceptions in the rule engine.** `decision_for` returns "not read" whenever the matched rule keeps mail away. Remove `_names_them`, the `read_replies` and `look_closer` paths, `Decision.exception`, `Stored.worth_a_look` and `_deserves_a_look` in `sync.py`. Sort rules stop writing `mentions`/`read_replies` (`sort_rules.rules_for`, its callers in `sorting.py` and `sortlab/lab.py`). Old rules that still carry them are simply ignored. The Rules settings page stops saying "replies / mail that names you still reach the AI" (`said` in `ui/features/settings/RulesSettings.tsx`, strings `rules.said.*`). Removing that false text is a small UI change: show it to the person.
  *Why:* the exceptions are what let company notices through.
- **1.2 Check the folder again just before judging.** In the agent's queue (`next` selection in `mail_agent.py`, before `task_for`), a conversation whose folder is in `KEPT_FOLDERS` is settled "skipped". This covers mail filed into Hidden later, moved by hand, and sent mail in a hidden conversation.
  *Why:* the decision made when an email arrived can go stale.
- **1.3 Learning skips hidden conversations.** `_conversations` in `bulk_learning.py` and `NOT_FROM_RULES`/`unjudged_count` in `mail_agent.py` exclude threads in `KEPT_FOLDERS`. Drop learning's "recent automated mail with a worrying subject" queueing. `WORTH_A_LOOK` stays only for raising importance by code.
- **1.4 Matters (D3).** `they_answered` in `modules/agent/module.py` stops calling `matters.link(..., start=False)` for hidden mail. `matters.context_for` leaves out conversations now in Hidden.
- **1.5 Chat and brief (D2).** Mail tools in `tools.py` and the brief's mail query in `briefs.py` follow D2.
- **1.6 Clean up what the AI already did with hidden mail (D6).** A one-time pass, plus the same steps whenever a folder or sender moves to Hidden: decline open suggestions (`suggestions.decide`), close open tasks (`matters.closeItems`), close matters with no conversation left on the read side (`matters.done`). Each with Undo. Nothing is deleted on Gmail.
- **1.7 Record why the AI read an email.** Each email stores the gate's decision ("read: no rule matched", "read: filed by Finance, read by AI", "hidden: kept by linkedin"), already half there in `messages.rule`/`messages.why`. Phase 3 shows it as a chip.
- **Tests (fake model):** one per path in section 1 (exception, moved later, moved by hand, learning, matter join, chat per D2), each proving the AI is never given the mail. Update `tests/test_rule_engine.py` (it asserts the old exceptions).
- **Done when:** the person's query on internal returns no new rows after a day of mail, and on Gmail a newsletter that names the person stays hidden.

### Phase 2: A matter's timeline in date order (backend + small UI; needs D7)

**Purpose:** read a matter top to bottom as it happened, and give the AI the same story.

- **2.1 Emails are the timeline.** Every email in the matter's conversations is an entry at its own date. Today an entry exists only for emails that arrived after the conversation joined, and joined conversations bring none of their earlier emails.
- **2.2 Started = the earliest email** in the matter, wherever it came from. When an older conversation joins, "Started" moves to its first email.
- **2.3 Linked = the first email of a conversation that joined later**, with its reason on the next line ("Why: same ticket PLM-1234"). Not a separate entry with a borrowed date.
- **2.4 Actions at their real time:** task added, date changed, done, closed, merged, file linked, suggestion accepted/declined (`_event` with `_now()` already does this).
- **2.5 Existing matters:** recompute from the emails once; action entries are kept as they are.
- **2.6 The AI reads the same order:** `context_for`'s "lately" comes from the same date-ordered list.
- **2.7 UI:** the timeline look stays (`Timeline` in `ui/features/today/matters/MattersTab.tsx`); only "Jump to start" (D7) is new. Mockup first.
- **Tests:** a matter started from a newer conversation, then joined by an older one, reads "Started (older) → email → Linked/email (newer)…" in date order, on screen data and in the AI context.
- **Done when:** the person's "linked, linked, started" matter on internal reads in date order.

### Phase 3: Sidebar and Sort page you understand by looking (mockup first; needs D1, D4)

**Purpose:** a new person looks at the screen and knows what's happening, with almost no text. One mockup canvas covers all of this; build only after approval.

- **3.1 Home names (D1)** everywhere: sidebar, Sort page columns, menus, New folder and Edit folder dialogs, empty states, `ui/strings/en.json` (`nav.home.*`, `mail.sort.*`, `folder.*`).
- **3.2 Homes fold.** Both homes fold like any folder. Default: Read by AI open, Hidden from AI folded. The person's choice is remembered (with the existing hidden-folders setting, `ui/shell/hiddenFolders`). The open folder is never folded away.
- **3.3 A look per side.** Hidden from AI keeps its eye-closed icon (`keptFromAi`), and its folders get the same closed-eye mark, so a folder's side shows without its home in view. The same mark appears on each email row in a hidden folder, and in search results.
- **3.4 Calendar is a system folder.** Its calendar icon back, a fixed place in Hidden from AI below the top K, never ranked or hidden under "Show all". If the Sort page found no invitations, it isn't shown.
- **3.5 Top K on both sides (D4), every folder listed (board 14).** Each side lists all its folders: the K biggest ticked and shown in the sidebar, the rest below them greyed out with an empty tick. Ticking one moves it up into the shown section; unticking moves it down. − / + resets the ticks to the K biggest. Calendar and No folder are always listed. Clicking a folder's name opens a modal with its emails (newest first, "Open … to see all"); a quiet "Rule" button on each row opens the same modal on its Rule tab (the senders or subject it matches, "the AI decides by …" for an AI folder, or "filed by the app" for a header folder), with Edit rule…. The page itself never expands. The Sort page's "Give the biggest [N]" control is on both sides, as a number field with − and + (any K, 0 to the number of senders). The sidebar's preview count (`HOME_PREVIEW` = 3 in `ui/shell/customMail.ts`) follows the same K.
- **3.6 Show the flow instead of explaining it.** On the Sort page: one small diagram, *Mail → your rules → Hidden from AI | Read by AI → folders → Priority*, with live counts on each step, replacing the explanation paragraphs. Folder sizes as short bars beside the numbers. Empty states as one picture and one action.
- **3.7 A "why" chip on each email** from 1.7: "rule: Jira", "AI: Finance", "Hidden: linkedin". Replaces the "why it's here" sentence in Priority.
- **3.8 Remove the "about" sentences** that the pictures now carry (`nav.home.*.about`, Sort page notes). Tooltips keep them for anyone who hovers.
- **Done when:** the person, looking at the mockup without reading, can say which mail the AI reads and how to change that.

### Phase 4: "Hide from AI" where you see it (mockup first; needs D5, D6)

**Purpose:** after seeing a group in Week or Matters you don't want the AI on, one action takes it off the AI completely.

- **4.1 One action, "Hide from AI",** on a matter, a Week item and an email (menu and the email's toolbar).
- **4.2 It asks once (D5):** everything from this sender, or just this conversation.
- **4.3 It does the whole job:** moves the mail into Hidden from AI (a sender folder, or the sender's existing one), makes the rule so future mail follows (`sorting.move_sender(..., refile=True)`), runs the clean-up from 1.6, and shows one toast with Undo that reverses all of it.
- **4.4 The reverse, "Let the AI read",** from a hidden email or folder, with the same follow-through.
- **Done when:** on Gmail, hiding a newsletter from its matter closes the matter, removes its suggestions, files its old and new mail in Hidden, and Undo brings everything back.

### Phase 5: Today cleanup (FOLDERS_PLAN Phase 6; mockup first)

Unchanged from `docs/FOLDERS_PLAN.md` Phase 6: system status off Today, the setup strip, brief coverage as a quiet line.

---

## 5. Order

1. Phase 1 (gate): backend, checked on Gmail and with the person's internal query.
2. Phase 2 (timeline): backend, then the small UI change with a mockup.
3. One mockup canvas for Phases 3 and 4 together; build after approval.
4. Phase 5.

Each phase is built only when the person says build.
