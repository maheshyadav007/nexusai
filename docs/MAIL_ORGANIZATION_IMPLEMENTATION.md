# Mail organization implementation

Implemented against `MAIL_ORGANIZATION.md`, 6 November 2026. Changes remain uncommitted.

## Delivered behavior

- Folder migration adds Exact/Smart mode and bounded descriptions, retains `in_priority`, converts existing rules, and adds Broadcast once per Home. Empty folders stay editable in Settings and are hidden from navigation.
- Priority considers main and extra folders, importance, waiting status, and the newest message's rule. Important has its own view, search filter, and unread count.
- Exact folder rules use full email addresses and literal subject prefixes. Existing free-form sender rules remain compatible. Personal rules precede starters and headers; overlapping folder matches follow sidebar order. Exact filing skips judgement, retaining the consequential Updates header exception.
- Triage receives accepted Smart descriptions, validates returned names, supports multiple folders, and cannot create folders. Suggestions need acceptance. Manual filing, unfiling, importance, and status remain authoritative. Accepted overlapping folders receive a merge offer.
- Settings, context menus, and chat support mode changes with prefilled rules/descriptions. Historical sorting has a separate estimate/confirmation step and cannot create old tasks.
- Archive/delete preserve conversation decisions and a local copy. Restore and Undo work offline. Server moves resolve current UIDs by Message-ID, ignore superseded operations, and respect never-delete. Local filing takes precedence over stale server locations. Restore checks are recorded.
- Durable, account-scoped learning normalizes sender/subject groups and submits at most 30 per batch. Manual learning limits each click to 30 new groups; automatic bulk arrivals process all new groups. Each group has aggregate statistics and two bounded samples. Seen groups are not submitted again. Complete response coverage is validated before saving; incomplete batches retry up to three times and can be retried explicitly.
- Onboarding, history completion, PST completion, and larger live downloads share the procedure. Small transport chunks remain one bulk arrival; overlapping imports are deferred durably.
- New uncertainty starts the interview before marking. Explicit answers update group importance and reach subsequent judgements; Today offers Continue or Skip and displays app-counted suggestions. Marking uses bounded pages and preserves manual choices. Only the newest 200 eligible conversations within seven days receive full judgement. Older unmatched, reply-capable conversations within 30 days appear together on Today without automatic tasks.
- `mail.organization` exposes progress, choices, merges, older reply candidates, rule coverage, recorded learning calls/input tokens, corrections, and restore checks. The bulk threshold is configurable as `agent.bulk_mail_threshold` in `backend/src/nexusai/kernel/defaults.toml`, default 50.

## Priority clarification

The SQL sketch shows ordinary Smart Broadcast mail because it matched no Exact rule, while the examples hide it. The implementation follows the examples: Broadcast is a narrow exception to that fallback. Importance, waiting-on-you, and Priority-enabled folders still override it. Ordinary unmatched replies retain the fallback.

## Verification

- Backend full sweep: 851 passed, one skipped, 12 speed tests deselected. The final affected-mail run passed all 147 tests, including the added compound/disabled legacy-rule regression.
- Speed suite: all 12 passed against a generated 100,000-message mailbox. Its fixture now includes event-bus migrations so the startup assertion represents a fully migrated Home.
- Python formatting, lint, strict typing, and import boundaries pass.
- Frontend type/boundary/hardcoding checks and 19 unit tests pass; production build succeeds.
- All three focused browser regressions pass: Exact filing/Important/Archive/Undo/Restore, changing an empty Smart folder to Exact by entering a prefix, and hiding empty folders after navigation.
- The broader browser suite is not clean (108 passed, 73 did not run). An untouched checkout at `3cfe603` reproduces the onboarding accessibility failure and outdated mail connection navigation test. Other broad UI failures were not individually baselined. Empty-folder expectations were updated to the new specification.

## Real-mail snapshot audit

The configured Home was opened read-only and backed up into an encrypted temporary database. The original database and server were not changed. No model was called. The temporary copy was removed afterward.

| Check | Result |
|---|---:|
| Stored messages | 16,028 |
| Conversation decisions preserved by migration | Yes |
| Conversations tested through archive/restore and trash/restore | 200 |
| Restores preserving conversation decisions | 400 / 400 |
| Unmatched sender/subject groups | 1,475 |
| Batches needed at 30 groups per call | 50 |
| Additional groups reserved on a repeat pass | 0 |
| Rule matches among the latest 200 messages | 181 |

Live model quality, actual onboarding token usage, and subsequent importance corrections still need measurement during use. The snapshot audit establishes migration, grouping, and restore behavior rather than model judgement quality.

## Follow-up verification: navigation and personalized context

- Renamed Priority inbox to Priority; Priority uses lightning, Important a tag, and Starred the star.
- Added Starred navigation, unread count, list and search filters. Existing message flags supply stars and sync through IMAP. Archived stars remain visible; Trash/Junk-only conversations are excluded.
- Confirmed PLM and Swarm starter defaults are Exact literal subject prefixes (`[PLM]`, `[Swarm]`) with Priority off. The earlier UI preview deliberately overrode Swarm with Smart/Priority-on sample settings; that was not the default.
- Agent category tools support mode, personalized description, sender and literal subject prefix. Category listing now exposes all these settings.
- Individual mail judgement receives Smart descriptions plus Exact category rules/descriptions. Bulk learning also receives category descriptions, rules and Priority settings. Exact matching remains deterministic, and the model cannot override Exact matches.
- Follow-up validation: 23 organization regressions, 2 targeted category-tool tests, 3 organization browser tests and 19 frontend unit tests passed. Frontend type/boundary/hardcoding checks, targeted Ruff checks and backend mypy passed.

## Follow-up: working sidebar context menus

- Built-in mail views offer Open and Mark downloaded mail as read. Server folders also offer Get the rest when more mail is available.
- Categories additionally offer Rename, Priority inclusion, mode change, settings opened to the selected category, historical sorting with an estimate and explicit confirmation, and confirmed removal that keeps the mail.
- Smart categories route mode changes through settings so required Exact rules can be supplied. Exact-to-Smart changes use the normal category update command.
- Writes show failures, disable repeated actions while pending, and remain retryable. Mark-as-read snapshots the current account and folder/category scope, includes secondary categories, handles more than one page, and uses the durable IMAP outbox. A partial interruption can be retried without duplicating completed work.
- Server folder hierarchy traversal now guards against malformed parent cycles.
- Validation: 27 organization backend tests and 4 organization browser tests passed, including all fixed folder menus, category rename, Priority/mode changes, selected category settings, sort preview, removal cancel/confirm, and preserving mail. Frontend checks (19 unit tests), production build, Ruff, mypy and diff whitespace checks passed.

## Flow audit: history download completion

Found and corrected a timing gap: `_ingest(live=False)` could emit `mail.bulkArrived` for a historical chunk over 50 messages. History ingestion now waits for `mail.historyFinished` rather than treating internal chunks as independent bulk arrivals. Live bulk downloads keep their completed-arrival event. PST continues to start grouped learning on import completion.

Validated with three tests: initial and additional historical downloads do not emit live bulk events; grouped learning caches known groups; a live bulk download split into small chunks avoids per-message judgements. Ruff checks passed.


## Agent timing and failure recovery audit

For the subsequent per-agent prompt/context audit, fixes and validation limits, see [context and prompts](AGENT_CONTEXT_AND_PROMPTS.md).

### Reset verification

The full Home reset already removes the new database state: grouped-learning cache/membership/batches/reviews, interviews, preferences and prompt versions, category settings, restore checks and failed mail operations. No additional per-table deletion is needed. A new regression seeds this state, resets a temporary Home, reopens it and checks empty learning/personalization/retry tables, removed learned/personal prompt files, and restored default category settings.

Updated the reset dialog to name categories/rules, Priority settings, learned groups, interviews, corrections and preferences, and explain that setup and learning start afresh. Pending reset blocks duplicate submission and dialog dismissal. Failure UI now shows backend details and no longer incorrectly promises that nothing was removed or that a partial reset can simply be retried.

Validation: 11 backend reset tests, both reset browser checks, frontend type/boundary/hardcoding checks and 19 frontend unit tests passed. The broader eight-test browser invocation had seven passes and one separate onboarding/Today accessibility failure (`label-content-name-mismatch`), which remains outside this reset change. Tests used temporary Homes and fake services; the real Home was not reset. Changes remain uncommitted.

Follow-up: the accessibility mismatch is now fixed. The account button's accessible name includes its visible initials and name, with spacing between the two; both use the same initials helper. Updated stale sidebar test names and improved accessibility failure diagnostics. All 12 onboarding/sidebar/reset browser tests now pass, including full-page accessibility scans and a focused check with the sidebar collapsed. Frontend checks and 19 unit tests also pass.

### Final combined validation before push

On 2026-11-06, the final combined backend suite passed: **914 tests**, one skipped and 12 speed tests excluded. Full backend Ruff, mypy (116 source files) and both architecture contracts passed. Frontend checks, 19 unit tests and the production build passed; all 23 desktop packaging tests passed. This supersedes the earlier partial/follow-up backend validation limits above. Windows executable packaging and installation remain subject to the hosted Windows workflow.

See [the timing and recovery audit](AGENT_TIMING_AND_RECOVERY.md) for trigger conditions, automatic recovery, explicit retries, verification and practical limits.

Fixed scheduler-loop survival and isolation, startup listener ordering and terminal-result reconciliation, stopped-run outcome handling, held interview/wrap-up recovery, failed-interview retry, unfinished-learning finalization, cancelled/failed batch retry state, quiet-hour obligation notifications, retention/retry of rejected IMAP operations, PST worker cleanup/exit validation and malformed record handling, possible mutation replay after model outages, the next turn's Stop-control race, and Today Retry command/error handling.

Validation: 882 backend tests passed (one skipped, 12 speed tests excluded); 84 follow-up regressions and 26 final dedicated recovery tests passed. Frontend checks and 19 unit tests passed; five organization/recovery browser checks passed. The later targeted checks cover changes added after the full suite began. No real mailbox was modified, and all changes remain uncommitted.
