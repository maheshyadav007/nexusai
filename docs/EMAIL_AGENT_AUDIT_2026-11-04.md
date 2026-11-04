# Email agents: reliability, context and personalization audit

Reviewed 4 November 2026 against `85b82f5` plus the composer/brief presentation changes in this working tree. This is a code and prompt audit, with isolated deterministic probes and primary-source research. It is not a claim that a live model was evaluated successfully on the user's mailbox. No real mail was reprocessed, sent, moved or used in research queries. Agent pipeline changes below are recommendations, not shipped fixes.

## Implementation follow-up

The findings below preserve the pre-implementation baseline. Reliability, shared context, scoped approved preferences, immutable brief artifacts, typed handoffs, timezone scheduling and queue controls have since been implemented. See [the implementation and verification record](EMAIL_AGENT_IMPLEMENTATION.md) for tests, model evaluation and remaining limitations. The historical probe scripts reproduce the earlier schema/behavior and are not current acceptance tests.

## Assessment

The foundation is useful: durable trigger records, a shared runtime, structured triage, approval boundaries, source-marked/untrusted mail, editable personal prompts, corrections, mailbox-derived context and a view of what the agent knows. But I would not yet describe this as dependable end-to-end email management. Several scheduling/state paths can lose coverage or conceal unfinished work, and personalization varies by entry point. Fix these before expanding agent autonomy.

The chief of staff currently exists chiefly as the Mail agent's prompt identity. There is no separate chief with a typed, accountable orchestration contract across the specialists. Adding more conversational agents would not resolve the delivery and state problems.

## Current agents and trigger map

Defaults below come from migrations/configuration, not a dump of the user's current settings. All configured schedules/triggers are visible through the registry; individual installations may override them.

| Role | Starts when | Context / intended result | Main concern |
|---|---|---|---|
| Mail agent / email chief of staff | Mail needing triage; per-email or held until hourly release; manual run/retry; answers to its questions | One thread, personal layers, corrections, mailbox facts, tools; `record_triage` ends the run and records status, importance, category, next action, optional draft/work/notes | Decision freshness and coverage; explicit choices can be overwritten |
| Reading past mail | Enough unjudged history has synced, or history sync finishes; manual read-more | Same Mail session, restricted historical-learning instructions; bounded notes, no historical notifications/work creation | Defaults to 400 emails; setup gates unrelated ongoing features |
| Learning wrap-up | Historical queue finishes and learned notes exist | Tidies learned notes, explains what was learned | Completion/state registration order can race |
| Know you better / interview | Once after historical reading reaches done; can also be started by the user | Profile plus learned notes; ask one question at a time, then propose four personal prompt saves | Skipping history also skips automatic interview; completion should be explicit rather than inferred from session existence |
| Morning brief | Daily 08:30 by default; manual schedule run | Open mail and chases, pending decisions, prior brief reactions; daily-prep instructions | Learning gate; missing mandatory task/deadline snapshot; stale brief visibility |
| Inbox review | Mondays 09:00 by default; first learning completion; certain tidy/priority checks; manual run | Sender/category aggregates; suggests filing rather than silently applying it | Shares Mail session; review marker advances before successful work |
| Hourly check/digest | Hourly schedule, disabled in initial migration; enabled by applicable mail mode | Releases held mail or summarizes recent decisions | One-hour floor and early watermark can skip digest coverage |
| Custom event agent | Configured `mail.received` or `mail.urgent` | Trigger prompt plus at most three triggering threads; persistent triggered session | All pending events assigned despite only three thread contexts |
| Scheduled task | Once, hourly, daily or weekly; run-now | User's prompt, prior schedule context, tools, short report | Queue cancellation semantics, timezone, priority and outcome reporting |
| Interactive chat | Ask agent, new chat, session reopen and user messages | General session prompt, profile/personal memory, attached/searched context, tools | Must share the same facts and decision policies as background agents |
| Draft helper | Manual reply-draft request, if no ready saved draft | Thread plus writing samples, draft-reply prompt and personal Markdown files | Bypasses full profile/memory/corrections context builder |
| Summary helper | Summarize / update summary | Thread messages or uncovered messages plus earlier summary | Cached coverage/version and source trust need evals; factual compression should not invent preferences |
| Compaction helper | Compact now or automatic compaction, when configured | Compresses history for subsequent runs | Lossy context is not authoritative task or preference storage |
| Deterministic timer | Due reminders, overdue board deadlines, follow-up dates | Notifications without a model | Deadline completion bug; local-time and restart semantics |

Evidence: `registry.py`, `module.py`, `triggers.py`, `scheduler.py`, `runtime.py`, `mail_agent.py`, `prompts/*.md` under `backend/src/nexusai/modules/agent/`; defaults in `backend/src/nexusai/kernel/defaults.toml`. Trigger dispatch order is schedules, custom triggers, live mail, wrap-up, interview. Default worker concurrency is three; triggered context retains 12 messages, mail reads at most eight recent thread messages / 20,000 characters, selected memory budget is 8,000 characters. The full prompt also contains other layers, so that is not a total context-token limit.

## Read-only snapshot of the running app

The running app reports Mail mode `both` (new-mail judgement plus hourly check), morning brief enabled at 08:30 daily, Inbox review enabled Mondays at 09:00, and the built-in mail-needs-triage trigger enabled. No custom schedules or custom event triggers were returned by their list queries. Historical learning is already `done`; therefore the fresh-Home zero-learning issue below is not currently blocking this Home. The registry lists Mail, morning brief, review, historical reader and interview. “Finished” interview is a registry/session classification, not proof that every proposed preference save was accepted.

The knowledge view reports authored profile/personal prompts, a correction layer, mailbox facts and mixed memory. It contains 66 unconfirmed learned notes and no confirmed-note entries; personal Markdown remains a separate authored source. The next improvement should be scoped confirmation/expiry of useful hypotheses, rather than treating all 66 as truths or asking the user to review them all at once. There is one stored brief reaction and one aggregated correction row in that snapshot, so behavior learned from feedback is still based on sparse evidence. No private note/email contents are reproduced in this report.

## Findings, ordered by impact

### 1. Event bursts acknowledge more email than they supply — P1, reproduced

`triggers.py:340–367`, `_start_custom`: five distinct pending threads become `threads[:3]` in the task, while every pending event ID is passed to `_dispatch`. On successful turn completion every associated event is settled. There is no explicit continuation for the omitted threads. An agent might independently discover them using tools, but that is not guaranteed coverage.

Isolated in-memory probe against the real method: **3 threads supplied; 5 events assigned to that run**. Fix by claiming only the bounded subset represented in the context, leaving the rest pending. Store per-thread outcomes; test 1/3/5/100-event bursts, duplicate events, failures and restart.

### 2. An overdue notification completes unfinished work — P1, reproduced

`scheduler.py:208`, `_overdue`, sets `work_board.done = 1` before notifying. Isolated probe: an unfinished deadline becomes `done: 1` merely because its date passed. Existing `test_agent_work.py::test_overdue_deadlines_notify_once_without_a_model` even expects it to disappear from `board.list`; that test preserves undesirable product semantics.

Add a separate `overdue_notified_at` or notification ledger. Only an explicit completion event may finish work. Notify once while retaining the obligation in the board, chief's context and brief. Planner tasks and legacy work-board deadlines also need a common definition of completion and deduplication.

### 3. Turning historical learning off blocks morning briefs — P1, reproduced

`triggers.py:198` returns early when the learning count is zero; `triggers.py:476` skips mail-brief unless learning state is `done`. `mailAgent.save` does not establish an alternative ready state. Probe: **learning state remains empty; brief is skipped**. This affects a fresh Home with history learning disabled, not every user who disables it after setup.

Separate `history_learning = skipped/done/...` from `mail_ready`. Briefs should use whatever current data is available and explain incompleteness. History reading must be optional; interview should also be independently available. Add fresh-install/skip-history/no-mail/partial-sync tests.

### 4. Work can finish before its trigger records are associated — P1, controlled ordering probe

`triggers.py:394` calls `runtime.dispatch()` before storing trigger status/session/turn. `runtime.py:558` submits a worker, whose completion callback reads associated running trigger records in `triggers.py:527`. The same pattern exists in learning wrap-up state registration.

A forced early-completion probe sees **zero associated events during completion, then a running event after dispatch returns**. This establishes the ordering hazard, not its frequency in production. A fast finish can leave trigger work appearing running until restart/recovery and create replay risk. Allocate the turn and claim its work atomically before submission, or introduce an explicit reservation protocol. Test with a completion barrier and crash points. Replay must use idempotency keys for every mutation; do not infer exactly-once delivery from one successful model response.

### 5. Human decisions and newer mail need version fences — P1, code-confirmed write path; concurrency scenario not reproduced

`mail_agent.py:790`, `Triage._apply`, protects user-set categories in applicable cases, but writes importance/status/next action/follow-up without a compare-and-set against the thread/input version used to generate the answer. A user correcting importance while a model is working can have that correction overwritten by the older result. Newer messages can similarly make a finished classification stale.

Keep `input_message_version`, per-field provenance/user override and decision version. Apply only if the source snapshot still matches and no newer explicit correction owns the field; otherwise reconcile/requeue. Validate combinations such as resolved + follow-up, unsupported deadlines and draft commitments in code. Retain uncertainty and source evidence rather than coercing every answer to confidence.

### 6. Digest/review watermarks describe attempts as success — P1/P2, code-confirmed

`triggers.py:425–475` updates `LAST_DIGEST` before dispatch finishes; `_digest_since` never looks earlier than one hour. Review writes its marker before a successful outcome. This can create incomplete catch-up or misleading completion after outages/failures. Model-held retry paths help but do not prove every outcome was covered.

Track requested, claimed, completed and failed intervals separately. Advance a completion watermark only after the intended artifact/outcome is durable. Backfill uncovered intervals with a bounded catch-up policy; show an explicit partial/failed indicator. A successful chat message alone should not certify that a filing review or brief did its job.

### 7. The brief does not get a guaranteed complete obligations snapshot — P1/P2, code-confirmed

`mail_agent.py:468–548` supplies limited inbox status lists and pending decisions. Planner tasks, reminders and due work-board obligations are not mandatory entries in `brief_task`; obtaining more depends on tool selection. Open-mail selection is inbox-based, so archiving must not be confused with completing an obligation. A latest-successful brief can also remain visible after today's run fails; timestamp alone is weak freshness communication.

Build a deterministic snapshot: overdue/today/soon tasks, commitments, reminders, unanswered incoming requests, promised outgoing work, chases, pending decisions and relevant changes since the last brief. Include counts, limits, source IDs and freshness. Lead with one decision/action. Show “Last successful brief” and partial/stale status when appropriate. Persist the artifact separately from chat history.

### 8. Personalization differs between agent and helper — P1/P2, code-confirmed

`knowledge.py:47` adds Settings profile (including tone/signature/VIPs), selected memory, and role-specific layers. Manual `draft_reply`, `mail_agent.py:1200–1240`, directly calls `prompts_builder.build_layers`, so it still gets personal Markdown prompts and samples, but omits the Settings profile and selected memory/corrections/mailbox layers that the Mail role receives. A draft generated automatically versus manually can sound or decide differently.

Use one purpose-aware context service. Every writer gets authored identity/tone/signature and relevant confirmed constraints. Triage gets sender/topic-specific corrections and outcome evidence. Brief gets priorities, complete obligations and brief preferences. Summary gets source-grounded facts with minimal irrelevant personal context. The remedy is consistent relevant context, not sending the entire mailbox to every helper.

### 9. Coordination is text-based, with a lifetime message cap — P2, code-confirmed

`tools.py:1150` counts all `agent_channel` messages by session, although the setting is `max_agent_messages_per_run`. A persistent agent can exhaust the budget across runs. Posting text and manually reading inbox messages is not a task assignment/acknowledgement protocol.

Count messages by run; add typed handoffs with purpose, owner, task ID, evidence/version, expected output, deadline and acknowledgement. Avoid broadcasting every email to every agent. The chief owns the decision queue and reconciles conflicting proposals against shared state.

### 10. Scheduling is not yet a priority policy — P2, code-confirmed mechanism; latency impact needs measurement

Schedules/custom triggers dispatch before live mail; reviews/history share the Mail session. Three workers do not guarantee fresh important mail receives prompt service. Pending schedules are looked up by ID without rechecking enabled status; deletion skips them, disabling may not cancel already queued work. Run-now may intentionally allow disabled schedules, but that intent needs explicit provenance. Schedule times are persisted as naive local strings, without a named timezone/DST policy.

Separate manual and timer triggers. Define cancel/pause semantics for queued work. Use priority with aging (fresh actionable mail before bulk learning/review), bounded background batches and per-thread write serialization. Persist timezone and local-calendar intent, UTC due instant and catch-up policy. Surface queue age, failed/held work, last successful outcome and retry control.

## Prompt review

| Prompt | What is already useful | Change recommended |
|---|---|---|
| Mail | Personal instructions outrank sender prestige; separates importance from interruption; structured triage; historical mail cannot notify/create work; proposes drafts rather than sending | Replace “don't hedge” with calibrated uncertainty and a bounded review path. Current recruiter example says `notify true` for “this week”, conflicting with the rule that later-this-week requests can wait. Distinguish thread-specific corrections from permanent sender policy. Require evidence IDs for deadlines/commitments and validate outputs in code |
| Historical learning / wrap-up | Notes are marked untrusted; old mail is prevented from generating current work | Track source/time/confidence, distinguish expired projects, confirm only consequential inferences, and avoid treating a small sample as complete knowledge |
| Interview | Confirms inferred information, asks one question at a time, asks approval for authored prompt saves | Support skip/resume and partial results; handle contradictory answers and preference expiry; save each accepted fact with provenance and version, not only a whole prompt blob |
| Daily prep / brief | Short, actionable, one-minute brief; incorporates reactions; avoids redundant tell messages | Guarantee obligations snapshot, freshness and source links; no duplicated tasks/drafts; distinguish content correctness from presentation preferences |
| Inbox review / digest | Aggregate view and suggestion-based filing protect the user from silent cleanup | Define exclusions for unfinished/high-risk mail, preview counts/examples, reversible batches and versioned completion; preserve coverage across outages |
| Session / scheduled | Search first, use tools, source markers and short outcome reporting | Shared policy for ownership and idempotency; distinguish proposed from completed outcomes; protected scheduled chat acknowledgement is a UI warning, not a broader tool grant |
| Draft | Match writing samples; placeholders for unknown commitments; body-only | Shared authored profile + confirmed constraints; recipient/account-aware style; never convert a guessed date/decision into a promise |
| Summary / compact | Incremental summary reduces work; compaction bounds context | Verify coverage against message IDs/version, preserve unresolved asks/dates/negation, keep citations; do not use compressed chat as the canonical ledger |

Prompt safety instructions are useful but must be backed by actual tool permissions, approval checks and validated writes. Keep the existing untrusted-mail and approval boundaries while improving context.

## Personalization: what exists and what is missing

Physical assembly order: shared system prompt → role prompt → Settings profile → all personal Markdown prompts → corrections (Mail only) → brief preferences (daily-prep only) → mailbox aggregates (Mail only) → selected memory. Runtime then supplies the current run, task/thread and retained conversation context. The Mail prompt explicitly tells the model to prioritize authored personal instructions; concatenation order itself is not a software-enforced policy. `knowledge.view` and preview expose much of this, which is a strong transparency foundation.

The intended design is a **feedback loop implemented through prompt engineering and context updates**. Model-weight training is out of scope. Corrections already become future instructions, repeated category corrections can suggest a rule, and recent brief likes/dislikes/comments influence later briefs. Chat turn ratings are stored, but are not yet incorporated into this prompt-improvement loop.

Problems to fix:

- `feedback.layer` says to repeat a correction from now on, even when it was an exception. Contradictory sender corrections can coexist. Capture the old decision, task context, scope, undo and expiry; ask whether a recurring pattern is a rule.
- `signals.py` describes `SUM(read)` as opened mail. Read state can come from synchronization, bulk actions or another client. Reply counts reflect own-message participation in a thread, not necessarily a reply after that incoming message. These are useful observations with caveats, not attention ground truth.
- Some sender/contact queries span accounts; use an explicit personal/work/account scope rather than accidental pooling. Writing samples are two 400-character snippets; recipient/relationship/language and accepted edits offer better targeting.
- `memory.relevant` uses lexical overlap and a fixed character budget. Learned notes are bounded text without a full confidence/expiry/contradiction lifecycle. Move to individually sourced, scoped, versioned facts and preferences, with deterministic inclusion of important authored constraints.
- All personal prompt Markdown is added broadly. Route relevant sender/topic/project preferences and avoid conflicting or oversized global instructions.
- `brief_feedback` is keyed by session/day; updating a same-day reaction does not replace its original brief excerpt. Bind feedback to the exact artifact/run version, including regeneration.

## The high-level interaction signals TODO

Recovered: `docs/KNOWN_PROBLEMS.md:70` asks for implicit opened/finished/ignored signals; `docs/FEATURES.md:323`, PMT-7, proposes approved prompt/rule changes from corrections; PMT-4 and PMT-5 cover preview testing and prompt version/restore.

Recommended event record:

```text
interaction_id, occurred_at, actor(person/system/agent), origin,
account_scope, artifact_id, artifact_version, run_id, source_message_ids,
action, field, old_value, new_value, exposure_id, undo_of
```

Use stable IDs, a retention policy and derived features; raw email bodies and keystroke collection are unnecessary for this loop. Confidence belongs in the derived interpretation, not as an invented property of the user's click.

| Observed action | Appropriate interpretation | Do not infer |
|---|---|---|
| Explicit importance/category/status correction | Strong evidence about that decision; possible scoped preference candidate | A permanent global sender rule from one exception |
| Reply actually sent; task explicitly finished | Concrete outcome; update commitment state | The entire generated answer or priority ranking was correct |
| Draft accepted with edits | Separate content corrections from style edits; learn scoped wording preferences | Acceptance of unsupported facts or every unedited phrase |
| User opens an item / sustained foreground reading | Weak interest signal, if actually exposed | High importance; open/read equivalence |
| No open or no action | Usually unknown; only interpret after exposure and time/availability context | Dislike or low importance by default |
| Approval accepted | Permission for that particular action | Endorsement of every upstream judgement |
| Brief like/dislike/comment | Artifact-specific satisfaction and explicit preferences | Correctness of every fact in the brief |
| Brief clicked / glow settled | Presentation acknowledgement only | Positive learning reward |
| Bulk read/archive, sync flags, agent mutations | Operational state with actor provenance | Personal preference or attention reward |
| Undo / declined preference / changed goal | Revoke or narrow the earlier inference | Another contradictory permanent instruction |

Pipeline: **observe → aggregate scoped evidence → propose a specific preference → confirm consequential changes → version it → retrieve it on the next relevant run → replay/evaluate → monitor and support undo**. Low-risk presentation preferences can adapt conservatively; actions with consequences still use existing permission checks. Each learned preference should explain “why I think this” and allow an exception.

The adaptation mechanism stays entirely in prompts and context: translate feedback into a precise, scoped instruction; resolve conflicts with existing preferences; version the change; retrieve it for relevant agents; and check subsequent outcomes. No model-weight training or bandit optimization is planned.

For example, “this recruiter email was important because my job search is active” should produce a candidate instruction such as “While my job search is active, prioritize direct interview and availability requests.” It should not become “all recruiter mail is important.” The instruction can be shared with triage and briefing; the draft helper receives the relevant writing or commitment constraints. When the user says the search has ended, retire that instruction. System safety and permission rules remain outside automatic personalization edits.

## Recommended chief-of-staff architecture

```text
Mail sync / clock / person
          ↓ durable input + dedupe + coverage ledger
Deterministic router and priority queue
          ↓ purpose-specific, versioned context snapshot
Mail judgement → commitments / tasks / draft candidates
          ↓ validated facts, evidence, ownership and source versions
Chief of staff → one ranked decision queue + brief + justified interruptions
          ↓ explicit actions and observed outcomes
Preference curator → scoped proposals → confirmed versioned memory
          ↺ next relevant context snapshot
```

Keep orchestration and completion deterministic. Use a specialist only where its purpose justifies a separate run. The chief reconciles and prioritizes; it does not need a fresh multi-agent discussion for every message. Shared task/commitment state is authoritative; chat is the explanation and interaction surface. A committed output contract should include `input_version`, `evidence`, `status`, `next_action`, optional confidence/review reason, proposals and idempotency keys. Record the model, prompt/context version and tool outcomes for diagnosis.

## Delivery sequence and acceptance checks

1. **Reliability first:** burst coverage, overdue semantics, history-independent readiness, dispatch reservation, version fences and completion watermarks. Tests must assert actual final database state under concurrency, failures and restart. Do not run a broad live re-triage to validate fixes.
2. **One context service:** profile/style/constraints available consistently; scoped memory and feedback provenance; a complete brief snapshot; timezone-aware queues and priority. Add inspectable per-run context snapshots and evidence links.
3. **Personalization loop:** instrument meaningful interaction events, support undo/expiry/conflicts, propose editable preference changes, replay on recent consented/synthetic cases before adoption. Distinguish UI acknowledgement from learning.
4. **Measured chief orchestration:** typed handoffs, ownership, bounded specialist runs, queue/SLO dashboards, shadow evaluation before broader automation.

There are currently **27 synthetic mail evaluation cases** in `backend/evals/mail_cases.json`. `mail_eval.py` checks a single judgement's selected fields and uses the configured model; it is a useful start, but it does not measure the full running system, real user-specific performance, races or long-term preference learning. The live-model eval was not run in this audit. `docs/KNOWN_PROBLEMS.md:124` explicitly records that the prompts were tuned on these same 27 cases, so the previously recorded 26/27 result is an in-sample smoke-test result, not held-out quality evidence. That document also leaves live prompts, company-model tool parsing, thinking-model behavior, search relevance and interview-save behavior pending real-world verification. These are release gates for dependable email management, not evidence that the fake-model tests validate the provider integration.

Expand into temporal scenarios: incoming → triage → human correction → follow-up → reply → completion; profile changes; two accounts; new/rare sender; archived unfinished request; conflicting preferences; ambiguous no-reply consequences; indirect deadlines; multilingual threads; bulk flags; outages; duplicate events; denied approvals; injection; regenerated brief feedback. Repeat model trials and keep a held-out set distinct from prompt examples.

Track: missed critical/actionable mail (recall), false interruptions, deadline extraction/commitment correctness, stale or lost work, duplicate mutations, contextual personalization consistency, draft factuality and edits, brief coverage/freshness, latency/queue age, tokens/cost and user time saved. Report per person/segment, not only a pooled score. Use code checks for deterministic invariants and blinded human review for subjective relevance/style; model graders can assist but should not be the only judge. Set targets after a measured baseline; zero silent event loss and zero unauthorized sends are invariants, not average-quality goals.

## Research basis and limits

- [Anthropic: Building effective agents](https://www.anthropic.com/research/building-effective-agents): start with the simplest workflow that meets the need. This supports deterministic orchestration here; it does not prove NexusAI's current prompts are accurate.
- [Anthropic: Effective context engineering](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents): curate high-signal context and retrieve relevant material instead of growing every prompt indiscriminately. This informs the purpose-specific context service.
- [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents): evaluate outcomes of the complete agent/harness, using complementary graders and repeated trials. This informs stateful replay and mutation checks.
- [ACE research paper](https://arxiv.org/abs/2510.04618): structured incremental context adaptation is relevant to preference curation. Its benchmark results are not evidence of improved email management in this app.

## Validation performed

Isolated in-memory probes called the existing `_start_custom`, `_overdue`, `consider_learning`, `_start_schedule` and `_dispatch` methods, with fake dispatch/model gates and synthetic records. They reproduced findings 1–3 and the controlled early-completion ordering in finding 4. The probe script and result transcript are preserved alongside this report in `docs/audits/`. Other findings are identified as code-path analysis or scenarios needing measurement/reproduction. Browser QA uses a separate synthetic Home and fake model; it is not an email-quality evaluation.
