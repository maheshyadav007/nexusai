# Email management implementation

Scope: the 4 November email-agent audit and subsequent feedback clarification. Keep `Today`; use recorded names elsewhere. Space Grotesk headings/navigation, Inter reading text. Pets excluded. Existing approval boundaries remain authoritative. No model-weight training or bandit optimization.

## Checklist

- [x] Atomic dispatch/trigger registration, restart and race regression coverage
- [x] Bounded burst claiming without dropped trigger coverage
- [x] Overdue notification separate from completion
- [x] Brief readiness independent of optional history/interview
- [x] Freshness fences for human corrections and newer incoming mail
- [x] Successful-outcome digest/review watermarks and catch-up
- [x] Complete, versioned brief artifacts and artifact-specific feedback/freshness UI
- [x] Purpose-aware shared context for triage, draft, brief and chat
- [x] Scoped feedback observations, explicit preference proposals, conflict/expiry/undo
- [x] Preference versions, preview, restore and inspectable run context
- [x] Typed handoffs, per-run message budgets and accountable ownership
- [x] Queue priority/aging, pause/cancel provenance, timezone-aware scheduling
- [x] Accurate behavior signals with actor/account scope
- [x] Prompt uncertainty/evidence/commitment improvements
- [x] Held-out temporal eval fixtures and deterministic end-state checks
- [x] Agreed copy and font changes
- [x] Browser verification in both themes and responsive layouts
- [x] Appropriate backend/frontend checks, production build and healthy running app

Live-model quality is measured separately from deterministic correctness. Do not claim a live mailbox evaluation from synthetic model tests. Record implementation evidence and remaining limitations here as work proceeds.


## Delivered behavior and evidence

| Area | Implementation / acceptance evidence |
|---|---|
| Durable work | Turn creation and input reservation share a transaction. Failed registration rolls back before submission. Five-thread bursts preserve the two not represented in the first three-thread batch. Human corrections and newer messages invalidate stale triage; manual draft generation also rejects changed conversations. |
| Catch-up | Each account has its own durable judgement-ID cursor. Digest batches are bounded to 100 records, advance only after nonempty output, and retry without dropping the failed interval. A two-account test proves scopes/cursors are separate. Review success markers follow output. |
| Briefs | Immutable output artifacts survive unrelated chat replies and same-day regeneration. Reactions belong to the exact artifact. Snapshot includes tasks, reminders, work-board obligations, archived unfinished mail and pending decisions, with counts and limits. Known unfinished sync/judgement or omitted details produces a partial label. History reading can be skipped without blocking the brief. |
| Feedback | Stable interaction IDs retain actor/account/artifact/version/run and old/new values. Corrections, sends, task actions, explicit ratings and UI opens are observations. Read flags are never labelled actual opens; silence is unknown. Repeated patterns and review-agent curation create proposals, not active policy. |
| Preferences and facts | Person-approved instructions are purpose/account/address/topic scoped, expirable, pauseable and versioned; revision conflicts reject stale edits. Available evidence appears with history. Check scope is deterministic; AI preview judges at most three local conversations without applying tools. Restore creates a new active revision. Source-scoped inferred facts stay untrusted; confirmation preserves expiry. |
| Shared context | Profile/tone/signature and authored constraints reach manual drafts and agent runs. Retrieved facts and approved preferences carry source/version information. Actual model context remains inspectable. |
| Coordination | Typed assignments retain recipient, purpose, expected output, evidence and owner turn. Missing reports become blocked; only the recipient can report. Message budgets reset per run. These are reported outcomes, not independent verification of every action. |
| Scheduling | Named IANA zones persist. DST gap/fold tests verify the policy. Queue exposes pending/running/failed, age, errors and retry/cancel; failed work is visible outside collapsed maintenance and contributes to Cockpit attention. Automatic pending work is cancelled on pause; Run now retains explicit provenance. |
| Summaries | Canonical source IDs, hashes and supplied character offsets replace count-only coverage. Older backfills and changed sources are detected. Oversized messages advance across bounded updates; encrypted or omitted text is marked partial. |
| UI | Space Grotesk headings/navigation plus Inter reading text; Today retained, Your brief / For your decision / First meeting / Approve applied. AI waits reserve an output surface immediately; moving generation light follows actual model generation, distinct from static identity rims and brief attention glow. Ordinary loading stays neutral. Summary and acknowledged brief retain stronger borders/shadows. |

## Verification — 4 November 2026

- Full backend suite: **801 passed, 1 skipped**, with 12 performance tests deselected. Two LangGraph experimental streaming warnings remain.
- Latest account-scope/runtime follow-up: **190 passed**, including the added two-account digest test and affected email/chat/brief/learning workflows. The full-suite run began before that final scope patch; this focused run covers the changed paths.
- Performance suite: **12 passed**. Ruff formatting/lint, mypy (112 source files) and import-boundary checks passed.
- Frontend: typecheck, hardcoded-value check, import boundaries and **19 tests passed**; production build passed.
- Connected-model prompt evaluation: **24/24**, two trials of 12 held-out invented cases, using ChatGPT provider `gpt-5.6-sol`. The original 27 tuned cases remain an in-sample smoke suite. [Raw results, prompt hashes and model metadata](audits/mail_holdout_results_2026-11-04.json) are retained. Omitted/null notify is normalized to no notification, matching the sent-mail prompt contract. This is one synthetic persona and selected judgement fields, not real-mailbox or whole-agent quality certification. No prompts were tuned on these held-out results.
- Synthetic browser Home on separate ports verified light/dark appearance, a 900px layout, computed fonts, approve → pause → restore, read-only AI preview and stale-preview clearing, named-zone save/display, immediate summary generation and completed border, immutable brief arrival/glow → interaction border, and managed composer lock → Still proceed → Lock input.
- Browser verified right-docked chat at **480px**, explicit full-page → Attach to right panel, and New chat control. Floating view remains disabled. Horizontal Settings dividers are preserved. A discovered narrow-dialog overflow was fixed and its Close button verified.
- Forced empty-result schedule surfaced in Cockpit with an attention count and Retry. A subsequent successful retry cleared the failed queue. A backend outage/restart verified event-stream recovery without reloading the browser; a closed proxy response now gets a bounded reconnect attempt.
- Running app restarted on frontend **4000** / backend **4100**. Startup recorded an **upgrade backup before migrations** and completed successfully; Home readiness and the new Preferences tab/font pairing were verified against the running build. No broad live-mail re-triage, test send or destructive mail action was used.

## Boundaries and remaining work

This implements the agreed reliability/context/prompt-feedback tranche. It does not promise perfect email management. Live company-provider parsing, real incoming/sent workflows, brief coverage, multilingual and multi-person quality, provider latency/cost targets, and long-term preference usefulness remain release checks in [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md).

- Semantic conflicts are exposed as dated/versioned instructions and clarification guidance, with manual edit/pause/restore; there is no complete semantic conflict adjudicator.
- Address scope matches an address appearing in supplied conversation context; it is not an authenticated current-sender-only policy. Topic scope is a literal phrase. Scope check inspects at most 100 recent local conversations; AI preview at most three.
- Authored legacy Markdown remains broadly included. Source-less legacy facts cannot retroactively acquire missing account/source evidence and stay untrusted when inferred. External file edits are read on the next run but are not a full prompt-version audit trail.
- Chat ratings and opens are recorded evidence. No automatic style learning from unsent draft edits, item-level brief ratings, inferred dislike from ignored items, or weight training is implemented. The interaction ledger still needs explicit retention/pruning controls.
- A completed chat is not proof of a handoff outcome. Blocked assignments require review; there is no separate autonomous chief process or independently verified handoff-completion service.
- New brief artifacts are versioned; legacy migration captures the latest eligible successful schedule chat because older inputs were not recorded. Local glow acknowledgement remains browser-local and is not a learning signal.
- Browser QA uses synthetic mail and a fake provider for deterministic interaction timing. The held-out prompt run uses the configured real provider separately. The Home-specific remembered-chat reset and other unrelated known problems remain outside this tranche.
