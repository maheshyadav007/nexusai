# Folders: one tree, Priority on top, two homes

Status, 2026-11-23 (evening): **built**, on branch `conversations`. Phases 0–5 and 7 are done, Phase 1 mostly (see "What was built" below). Phase 6 (Today cleanup) is not built: it needs a mockup first. The seven decisions in section 3 were taken as recommended (D1–D7).

> **The idea.** Today the sidebar mixes three different things and calls them all folders: a filtered view called "Inbox", folders the AI reads, and folders kept from the AI, with "Automated" drawn as if it contained its siblings. People can't tell what clicking anything will show. This plan makes mail work like a file system: **one tree of folders, each with settings** (its rules, an optional plain-language description the AI files by, Show in Priority, and more later). Two homes at the top, **Inbox** (everything the AI reads) and **Kept from the AI** (everything it doesn't), and a **Priority** view above them. A parent always shows its own items plus everything under it. New features become new folder settings, not new screens.

---

## What was built (2026-11-23)

- **Storage:** `mail_categories.parent` (migration `mail_folder_tree_001`); names unique across the tree, case-insensitive, checked in `modules/mail/folders.py` (`check_name`) on create, rename, split, sorting and agent saves. Homes are not rows: a folder with no parent is at the top of the home its `ai_reads` names; folders inside take their home's side (`folders.move`).
- **Upgrade, once per Home** (`_folder_tree_upgrade`, marker `mail_folder_tree_upgrade_001`): `Automated/x` becomes `x` at the top of Kept from the AI (the next free name on a clash, e.g. `linkedin 2`); `A/B` becomes `B` inside `A`; an exact folder whose every rule keeps its mail from the AI moves to Kept from the AI. Rename carries threads, rules, rule names and the rule stamped on each email (`_rename_folder`).
- **Parents include children:** `store.IN_CATEGORY` is a recursive "this folder or anything under it" (`folders.in_tree`), used by lists, search and mark-read. Sidebar counts add children's unread (`folderTree` in `ui/shell/customMail.ts`).
- **Homes:** list filters `reads` and `kept` (`store.FOLDER_FILTERS`, in the inbox, not archived), routes `/mail/inbox` and `/mail/kept`, unread counts from `mail.folders`. `/mail/priority` is the Priority view (icon `priorityView` = Iconoir FolderSettings) with a "why it's here" line on each email.
- **One folder per email (D3):** rules no longer add `extra_categories`; the mail agent and bulk learning pick one; "Add to folder" moves the conversation. Old extras stay readable.
- **Rules follow the side:** a folder's own rule keeps mail from the AI only in Kept from the AI; in the Inbox it files and the AI still reads it. A rule can have any conditions, all must match (`SaveCategory.conditions`, `categories.preview` counts matches without saving).
- **Split (board 12):** `categories.mixed` lists folders with senders on both sides and a suggested name; `categories.split` splits (or `undo`); shown at the top of the Sort page.
- **UI:** sidebar homes (`ui/shell/HomeNav.tsx`), Gmail/server labels under More, menus as board 8, the New folder dialog (`ui/shell/NewFolder.tsx`, board 11), Edit folder with "Inside", Sort page wording and "No folder" cards (board 9), the "biggest" count fixed, AI-suggested folders tickable on the Sort page (D6).
- **Phase 1:** 1.1 the "stale" brief was not a failure: freshness compared calendar days, so last evening's brief read after midnight said stale; now it's stale only once a scheduled morning brief should have replaced it. 1.2 the brief prompt no longer writes coverage as a bullet; the quiet line under it says so. 1.3 the one-email folders are gone from the test instance; sorting makes only the biggest 3. 1.4 and 1.5 are checked on the real mailbox after shipping.
- **Not built:** Phase 6 (needs a mockup), Phase 8. The Sort page's "+ New folder" stays a quick name field (a folder there is filled by dragging senders), not the full dialog.

## 0. Picking this up in a new session

1. Read this whole file, then `docs/MAIL_ORGANIZATION.md` (the sorting engine that runs before the AI) and the "Object model" section of `docs/MATTERS_PLAN.md` (the item-kinds registry we reuse).
2. Open the mockups (section 2). Every UI task below has a board there. **Build what's drawn; don't redesign.** Any UI change not drawn needs a mockup and the person's approval first.
3. Ask the person the seven questions in section 3 if they haven't answered them. Their answers change tasks 2.x.
4. Memory rules that apply (`~/.claude/projects/-Users-maheshyadav-Projects-nexusai/memory/MEMORY.md`):
   - **Mockup before any UI change**, then wait for approval.
   - **Mail is the product.** Check changes on the real mailbox (instance on :4000), not only tests.
   - **Never delete on Google's server.** Moving mail in this app must not delete anything in Gmail.
   - **No real-model evals without asking.** The fake model in tests is free.
   - **Throwaway Homes share the Keychain.** Set `NEXUSAI_SECRETS_TEST_FILE` on any scratch server.
   - **Keep it simple.** One phase at a time; each must pass its check before the next.
   - **No hardcoding in UI.** Theme tokens and `ui/primitives` only.
5. Instances: real `make -j2 backend serve` (:4000/:4100), test `make -j2 test-backend test-serve` (:4001/:4101). Playwright e2e uses :4000/:4100, so stop the real instance first, then restart it after `npm run build`.

---

## 1. Why we're doing this

What the person saw on 2026-11-22/23, and what each part of this plan fixes:

| Problem seen | Cause | Fixed by |
|---|---|---|
| "Automated" looked like it contained linkedin, beehiiv, axisbankmail; clicking it showed none of them | Folders named `Automated/x` are drawn indented under Automated, but opening a folder shows only mail filed directly in it (`IN_CATEGORY` in `modules/mail/store.py` is an exact match) | Parents include children (Phase 3); the two homes replace Automated in the sidebar (Phase 4) |
| "Inbox" said 22 while folders held thousands | The sidebar's "Inbox" is really the **priority** filter (`FOLDER_FILTERS["priority"]` in `store.py`; label `nav.priority` = "Inbox") | Rename it Priority; add a real Inbox home (Phase 4) |
| No consistency between the AI side and the kept side | The AI side has a home (Inbox) and the kept side doesn't; folders under Kept are a mix of the catch-all and sender folders | Two homes of the same shape (Phase 4) |
| Same folder name on both sides (Job search, Shopping, Travel) | Sorting decides by sender, so one folder can hold read and kept senders | One folder, one place; split mixed folders once (Phase 2) |
| Eight one-email folders under Automated on the test instance | Unknown: older sort or an agent moving senders (task 1.3) | Investigate; the split/migration review cleans up |
| Sort page "Give the biggest [0]" while 3 folders exist | `ownNow` in `SortScreen.tsx` counts only fresh senders, not existing folders | Phase 5 |
| Wording: "Edit folder…" next to "Rename category…", "Remove category…" | Old strings | Phase 4 menus |
| New folder dialog: no side, no body rule, "Show in Inbox" | Old `NewCategory` in `ui/shell/CategoryNav.tsx` | Phase 5 dialog |
| Today: "153 automated messages filed", a system status line, a confusing "Getting started" card | Status and setup mixed into the person's day | Phase 6 |
| Brief "Written 22 Nov 9:29 PM · Last successful brief. A newer br…" and a "Coverage: partial" bullet | A later brief failed or never ran; coverage shown as content | Task 1.1, 1.2 |

**Purpose overall:** a structure the person can predict (click a parent, see everything in it), that's the same on both sides, that the AI can use with a weak model (unique names, small choices), and that grows by adding folder settings instead of special cases.

---

## 2. Mockups

Canvas: **https://claude.ai/artifact/KXaVo81GjS2W1jT4cibnZU** (boards under "Final: Priority, two homes, folders as a tree"). Every "Now" panel is a real screenshot; every "After" uses real data from the instances.

| Board | Link | What it fixes |
|---|---|---|
| 8 · Sidebar | https://claude.ai/artifact/KXaVo81GjS2W1jT4cibnZU#artboard-SideMisc | Priority, the two homes, top-3 + Show all, Starred/Sent below, folder and home right-click menus |
| 9 · Sort page | https://claude.ai/artifact/KXaVo81GjS2W1jT4cibnZU#artboard-SortMisc | Same words as the sidebar; "No folder" card per side; Inbox \| Kept switch; correct "biggest" count |
| 10 · Priority icon | https://claude.ai/artifact/KXaVo81GjS2W1jT4cibnZU#artboard-PriorityIcon | Shows the options. **Chosen afterwards: Iconoir `FolderSettings` (folder with gear)**, which isn't one of the drawn options; board 8 uses it |
| 11 · New folder | https://claude.ai/artifact/KXaVo81GjS2W1jT4cibnZU#artboard-NewFolder | One dialog: Name (unique), Inside, AI decides / By rule, Show in Priority, file existing |
| 12 · Split | https://claude.ai/artifact/KXaVo81GjS2W1jT4cibnZU#artboard-Split | One-time review that splits Job search, Shopping, Travel |

Earlier boards 1–7 on the same canvas are built (step 1 and steps 2–5, commit `efcc282`). Board 7 (Sort cards) is the base the Sort page change edits.

---

## 3. Decisions still needed from the person

Ask these first. Recommendations are what I proposed; the person hasn't answered yet.

| # | Question | Recommendation | Why it matters |
|---|---|---|---|
| D1 | Store the tree as a **parent** setting per folder, or keep paths like `Projects/Alpha` in the name? | **Parent setting**, plain unique names | With paths, renaming or moving a parent must rewrite every child's name in threads, extra folders, every rule, the rule stamped on each email and the kept counts. With a parent setting, moving is one field and nothing else changes. Unique names make the path unnecessary for identity. |
| D2 | Gmail labels (Notes, ✔✔): where? | A read-only **"Gmail labels"** group under More | They come from Gmail, have no rules and no AI side, and can hold read and kept mail, so they break "one folder, one side" if placed under Inbox. |
| D3 | Can an email be in several folders? | **One folder per email**; a separate tags feature later if wanted | A tree means one place. Today mail can have a main folder plus `extra_categories` (several smart folders). |
| D4 | What do Inbox and Kept from the AI show? | Everything on that side that **isn't archived**; archived mail under More › Archive | Matches what "Inbox" means in Gmail, and stops both homes growing forever. |
| D5 | A rule with several conditions: all or any? | Keep **all must match** (how `modules/mail/rules.py` works: `all(...)` at line ~174); "any" later as one rule per condition | The mockup says "All of them must match". |
| D6 | AI side of the Sort page: default folders? | Offer the AI's **3 suggested topic folders**, ticked by default | The kept side gets its 3 biggest senders as folders; the AI side gets nothing today. Topic folders (Finance, Job search), not sender folders, because people's mail isn't one-sender-per-topic. |
| D7 | Prove the file-system model on made-up data before rebuilding? | **Yes** (Phase 0) | Mail is the product; we test the whole model on fake data before migrating the real mailbox. |

The person has already agreed: Priority view on top with the folder-and-gear icon; two homes; parents include children; unique names across the whole tree (case-insensitive); mixed folders get split; a folder's side comes from its home; filing order (below); plain-language filing instructions live only on folders; the New folder dialog as drawn. Recorded in memory as `nexusai-folder-tree-model.md`.

**Filing order (agreed):** rules that keep mail from the AI first → the person's other rules → the AI reads what's left and files by folder descriptions. The AI never overrides a rule. Each email records why it's where it is (`messages.rule`, `messages.why`).

---

## 4. The model (target)

```
Priority          view   (important, waiting on you, unfiled by rules, folders marked Show in Priority)
Inbox             home   (everything the AI reads, not archived)
  Finance         folder (rule or smart)
  Projects        folder
    Alpha         folder (smart: "anything about the Bosch migration…")
    Beta          folder (rule: body contains "beta")
Kept from the AI  home   (everything the AI doesn't read, not archived)
  linkedin        folder (rule per sender)
  Job alerts      folder
  (no folder)     the old catch-all "Automated": kept in the backend, never listed
Starred, Sent     views / system folders
More › Archive, Trash, Spam, Drafts, Gmail labels
```

- **Three kinds of node, one tree:** *system folders* (Inbox and Kept homes; Sent, Archive, Trash, Spam, Drafts mirror Gmail and can't be deleted or moved), *folders* (hold items; full CRUD), *views* (saved filters like Priority and Starred; hold nothing).
- **Every folder has settings:** `parent`, `name` (unique, case-insensitive, across the whole tree), rules, `description` + smart flag, `in_priority`. Side (`ai_reads`) is **inherited from the home**, never set per folder.
- **Items:** emails today. Documents and notes later (Phase 8), reusing the kinds registry `modules/agent/kinds.py` (`thread:12`, `doc:5`).
- **A parent shows its own items plus all descendants**; its unread count includes them.

---

## 5. Phases and tasks

Each task: what, why (purpose), where, done when.

### Phase 0: Prove the model on made-up data (D7)

**Purpose:** find out, before touching the real mailbox, whether one tree with settings really delivers every behaviour we agreed, and what migrating costs. Cheap to throw away; expensive to get wrong on real mail.

- **0.1 Throwaway Home with made-up data.** About 50 folders like the Sort page makes (both sides, some nested two levels), ~2,000 fake emails from ~100 senders, a few documents. Use `NEXUSAI_SECRETS_TEST_FILE` and the fake model only.
  *Why:* realistic size without spending the person's ChatGPT allowance or risking real mail.
- **0.2 One automated check per behaviour**, as backend tests:
  filing order; parent shows children; parent count includes children; rename doesn't touch anything else; move changes only the parent; unique names enforced on create/rename/move/split/agent; split of a mixed folder moves mail and rules with each half; Priority view contents; smart filing only on the Inbox side; Gmail system folders still match the server after a sync; a document placed in a folder.
  *Why:* each line is a promise made to the person; a test makes it checkable and keeps it true later.
- **0.3 Report** to the person: what passes, what doesn't, and the migration cost for their real mailbox (how many folders rename, how many clash, how many mixed).
  *Done when:* the person decides go / change / stop.

### Phase 1: Bugs found during review (independent; can run while the person answers section 3)

- **1.1 Why the brief went stale.** Today showed the 22 Nov 9:29 PM brief with "Last successful brief. A newer brief…". Find the failed or skipped run (`model_calls`, schedule runs, `modules/agent/triggers.py` `_start_schedules` and `_mail_settled`), fix the cause.
  *Why:* the brief is the first thing the person reads each morning; a stale one breaks trust.
- **1.2 "Coverage: partial" as a bullet.** The brief should wait for mail to be in and judged (`_mail_settled`), so partial should be rare; and coverage belongs as a quiet line under the brief, not in it (prompt `daily-prep.md` / `briefs.coverage`). Needs a small mockup if the UI line changes.
  *Why:* coverage is a note about the brief, not news for the person.
- **1.3 Where the eight one-sender folders came from** (test instance: amazon 1, iitm 1, steampowered 1…). Today's default is 3 (`TOP_CATEGORIES` in `modules/mail/sort_view.py`). Check older sorts and agent `move_sender` calls.
  *Why:* if an agent or old code still makes tiny folders, the new tree fills with clutter again.
- **1.4 Real account's Sort page offers "Skip sorting".** `mail_sorting.state` reads "ready", not "done", on :4000. Find out whether it was ever saved.
  *Why:* the page behaves as a first-time sort when it should be "change what's sorted".
- **1.5 Unverified on real data:** the sidebar-speed fix during a download (event batching in `ui/client/events.tsx`) and the suggested-task look (no suggestions existed). Check next time mail downloads and when a suggestion appears.

### Phase 2: Storage (needs D1, D3, D4)

**Purpose:** make the tree real in the data, so everything above it is simple.

- **2.1 Parent setting.** Add `parent` to `mail_categories` (migration). Homes are fixed rows. Side comes from the home.
  *Why:* moving a folder becomes one field; no cascade through threads, rules and emails.
- **2.2 Unique names.** Case-insensitive uniqueness on create, rename, move, split, and when an agent makes a folder; clear message naming where the clash is ("There's already a folder called Invoices, under Projects").
  *Why:* rules and the AI refer to folders by name; one name must mean one folder, especially for a weak model.
- **2.3 Migration of existing folders.** `Automated/linkedin` → `linkedin` under Kept from the AI; the catch-all `Automated` stays as the unlisted "no folder" of Kept; clashes go to the review in 2.4. Reuse the existing rename (`update_category` in `modules/mail/module.py`), which already updates threads, extra folders and rules.
  *Why:* the person's real folders move over without losing mail or rules.
- **2.4 Split mixed folders (board 12).** For each folder with senders on both sides: the read half keeps the name, the kept half gets a suggested name (from its senders/subjects), editable, checked for uniqueness; "Split all" with Undo. Uses `sorting.move_sender(..., folder=..., refile=True)` (exists).
  *Why:* one folder, one place; the halves were different sender groups that only shared a name.
- **2.5 One folder per email (if D3 = yes).** Stop adding to `extra_categories`; the AI picks one best folder. Keep existing extras readable until migrated.
  *Why:* a tree means one place; several places is a separate "tags" feature.

### Phase 3: Parents include children

**Purpose:** "click a parent, see everything in it", true everywhere.

- **3.1 One filter "this folder or anything under it"** replacing the exact match `IN_CATEGORY` in `store.py`, used by thread lists, search and counts.
- **3.2 Counts:** a parent's unread includes its children's (`category_rows` in `modules/mail/module.py`).
- **3.3 Folder chip** on each email in a parent's list, naming its actual folder.
- **3.4 Empty parents stay visible** (today `customCategories` in `ui/shell/customMail.ts` hides folders with no mail; with 3.2 a parent with children counts them).
  *Done when:* opening Kept from the AI shows linkedin's mail too, and the numbers match what opens.

### Phase 4: Sidebar and menus (board 8)

**Purpose:** the sidebar shows the model plainly.

- **4.1 Priority view:** today's "Inbox" (`FOLDER_FILTERS["priority"]`) renamed Priority, icon `FolderSettings` (add to `ui/icons/sets/iconoir.tsx` under a `priority` name change). Logic unchanged. Each email in it shows a short "why it's here" (waiting on you, from Finance…).
  *Why:* honest name for what it already is; the reason line stops it feeling random.
- **4.2 Inbox and Kept from the AI homes** with new list filters (AI-read, kept; not archived per D4), top 3 folders by size, "Show all (n)" only when more than 3. Remove the separate "Your folders" and "Kept from the AI" sections, the Automated row and the filter-icon button.
- **4.3 Starred and Sent** below the homes; Gmail labels per D2.
- **4.4 Right-click a home:** Open, Mark downloaded mail as read, New folder…, Sort senders….
- **4.5 Right-click a folder:** as board 8: "Show in Priority" (was "Show in Inbox"), "Rename folder…", "Folder settings…", "Remove folder…", plus "New folder inside…". Strings in `ui/strings/en.json` (`menu.*`, `categories.*`); menu in `ui/shell/MailNavMenu.tsx`.
- **4.6 Customize sidebar** (built in `SidebarEditor.tsx`) follows the homes instead of "Your folders / Kept from the AI".

### Phase 5: Sort page and New folder (boards 9, 11)

- **5.1 Sort page words:** columns "Inbox · the AI reads it" and "Kept from the AI"; plain folder names (no `Automated/`); a "No folder" card last on each side; card switch "Inbox | Kept" (`ui/features/mail/SortScreen.tsx`).
  *Why:* the Sort page and the sidebar must say the same thing.
- **5.2 Fix "Give the biggest [0]":** count existing folders too.
- **5.3 AI-side default folders (D6).**
- **5.4 New folder dialog** replacing `NewCategory` (`ui/shell/CategoryNav.tsx`): Name with live uniqueness; Inside (side follows); The AI decides | By rule (conditions: from, subject contains, subject starts with, [tag], header, body contains, has attachment; all must match); "AI decides" disabled inside Kept with the reason; Show in Priority; "Also file mail already here" with a live count (backend needs a count-only dry run of `_apply_category_rule`). Same dialog from the home menu, folder menu and Sort page.
  *Why:* one way to make any folder, with the body rule the person asked for.

### Phase 6: Today cleanup (mockup needed first)

**Purpose:** Today shows the person's day, not system status.

- **6.1 Remove** "153 automated messages filed" and the system status line ("Mail: Up to date… · 3 running") from Today; they live in the sidebar count and Tools › Cockpit.
- **6.2 Setup strip:** "Getting started" becomes "Finish setting up NexusAI · 3 of 6 done" at the top of Today, own look, only remaining steps with one action each, disappears when done; "Later" folds it into the sidebar as "Setup 3/6"; required steps (connect mail) keep it on Today.
- **6.3 Brief coverage** as a quiet line (with 1.2).

### Phase 7: Ship

- **7.1** Full backend suite, frontend checks, full e2e (update `e2e/sidebar.spec.ts`, `sorting.spec.ts` for the new names), then check on the real mailbox (:4000).
- **7.2** Commit, merge to `main`, start a Windows build (check status by curling GitHub's public API; never ask for `gh` login).

### Phase 8: Later (deliberately deferred)

- "Any" rule conditions (one rule per condition).
- Tags, if one-folder-per-email feels limiting.
- The AI choosing a folder in steps (top level, then child) once there are more than ~15 smart folders, to keep prompts small for a weak model.
- More folder settings: keep for N days, notify me, auto-reply.
- Documents and notes inside folders (Phase 0 checks it's possible).

---

## 6. Facts found in the code (so the next session doesn't re-derive them)

- Sidebar "Inbox" = `FOLDER_FILTERS["priority"]` (`modules/mail/store.py` ~line 284); label key `nav.priority`. Right-click "Show in Inbox" toggles `mail_categories.in_priority`.
- Opening a folder = exact match `IN_CATEGORY` (`store.py` ~line 810) plus `extra_categories`.
- Folder rows: `mail_categories` (name PK, mode exact/smart, description, ai_reads, in_priority, sender, subject). Sidebar numbers are **unread** counts.
- Rules: `rules.json` per Home; `MailRule.conditions` all must match; fields subject, subject_prefix, tag, body, sender, sender_exact, header, has_attachment. Skip rules are checked first (`Engine.match`).
- One rule per sender: `sorting.move_sender` is the single path; `refile=True` moves existing mail too; `apply` takes a `folder` per sender (empty = Inbox).
- Smart folders: the mail agent sees `name + description` of smart folders and returns `smart_folders` (`modules/agent/mail_agent.py` ~line 432, ~1034).
- Whole-folder side switch: `categories.update` with `ai_reads` (`_set_reads`); folders under Automated/Calendar are always kept.
- Hidden folders: sidebar layout `hidden` ids `folder:<name>` (`ui/shell/hiddenFolders.ts`).
- Sort page defaults: `TOP_CATEGORIES = 3` (`modules/mail/sort_view.py`).
