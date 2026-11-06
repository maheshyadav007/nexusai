# Agent timing and failure recovery

Audited against the implementation on 2026-11-06. These are application defaults; saved settings take precedence. This record describes the built-in agents and their supporting processes, rather than treating every background function as a separate agent.

## Timing

| Work | Trigger and conditions |
| --- | --- |
| Grouped learning | Completed onboarding/history download, completed PST import, completed live bulk arrival over 50 messages, or an explicit learning request. Requires the Mail agent and learning to be enabled. Internal historical chunks do not start separate learning passes. |
| Individual judgement | Eligible incoming inbox message; consequential generated-header-rule exception; eligible recent bulk conversations; or an explicit reassessment. Exact custom rules and user choices stay authoritative. |
| Mail agent modes | `each`: process eligible mail as it arrives; `hourly`: hold ordinary mail until the hourly release; `both` (default): individual judgement plus an hourly summary of completed judgements. Bulk learning does not wait for the hourly release. |
| Interview | Learning finishes with new uncertainty. An existing interview is reused; an initial attempt held for a model outage reuses its empty session. Applying learning choices is refused while account learning batches remain unfinished. |
| Morning brief | Default 08:30 daily in the schedule's saved timezone. |
| Inbox review | Default Monday 09:00 in the saved timezone, plus applicable upgrade/catch-up reviews. |
| Custom schedules | Saved once/daily/weekly schedule, or Run now. A manual run does not require the recurring schedule to be enabled. |
| Custom event agents | Enabled matching event trigger. Event identities prevent replaying the same event as a second queue entry. |
| Reminders, overdue deadlines, follow-ups | Due checks while time checks are enabled. Overdue/follow-up notices stay unconsumed during quiet hours and are attempted afterward. |

The app must be running for work to execute. The scheduler rereads the clock at most every five minutes, allowing recovery after sleep and clock changes. A missed recurring schedule produces one catch-up run and advances to a future occurrence, rather than creating a run for every missed interval. One-time schedules are consumed once. DST ambiguity uses the first occurrence; nonexistent local times advance by the DST gap.

A session cannot run overlapping turns. Global concurrency defaults to three running/queued sessions. Different agents can therefore wait for capacity. Work waiting for a person's approval stays waiting across restart.

## Failure policy

| Failure | Recovery and visibility |
| --- | --- |
| Slow or unreachable model server | A reply may be silent for up to 500 seconds before it fails (`chatgpt.timeout_seconds`), so slow servers can think before the first word; a streaming reply is never cut off while words keep arriving. Reaching the server fails after 30 seconds (`chatgpt.connect_timeout_seconds`). Both apply to the ChatGPT subscription, the company model and the connection test. A failure is then handled as "model unavailable" below. |
| Model unavailable before a possible mutation | Background work waits and retries. Default dispatcher retry interval is 60 seconds; configuration changes can wake it sooner. Rate limiting and daily caps also hold work. Mail download/rule processing continues independently. |
| Model unavailable after a tool may have changed data | Keep the run and its partial work, mark failure, and require review/manual retry. Unknown connector actions are treated conservatively. Automatic replay is allowed only when the recorded tools are known to be read-only. |
| Unexpected agent error, guard rejection, or missing required brief/review/digest result | Mark the run failed and expose its error in the session/queue. Retry is explicit. A digest cursor advances only after a successful result, so failed summaries do not consume unseen judgements. |
| Run stopped by the person | Do not mark it successful. A stopped learning batch requires explicit retry rather than automatically restarting. Completed judgements are retained. |
| Group-learning failure or incomplete group result | Up to three batch attempts, then a visible learning failure. Today, learning settings, and Cockpit queue retry paths reopen the corresponding learning state. Explicit retry can also restore previously cancelled batches. |
| Failed interview | Today exposes the failure and Retry creates a new attempt while keeping the failed session for review. An initial model-held interview automatically reuses its session. |
| App interruption | Running work resumes from its saved checkpoint. If a terminal turn was committed before its queue callback ran, startup reconciles its saved result instead of executing the completed job again. Listeners are registered before recovered workers resume. |
| Scheduler/check failure | The timer remains alive. Independent reminder, deadline, follow-up and schedule checks are isolated so a failing check does not stop the others. Pruning is marked complete only after success. |
| Mail connection failure | Reconnect with exponential delay, default 2–300 seconds. Authentication rejection remains a visible failure requiring corrected credentials. |
| IMAP operation rejected repeatedly | After repeated failures ending in a server rejection, retain the operation and its payload, mark it as needing attention, notify the person and continue other sync work. Cockpit → Pipelines → Mail sync → Run now resets failed operations for retry. Never-delete refusals remain intentionally non-retryable. |
| PST app interruption | Retain committed import position and resume after reopening. Duplicate detection preserves previously imported mail. |
| PST worker/file failure | Mark the import failed for explicit resume. Reap the failed child before another job starts. A completion marker with a nonzero exit code is not success. Malformed message bytes are counted as failed records rather than aborting a whole batch. |

A finishing worker releases only its own Stop control, so it cannot accidentally remove the next turn's control when completion starts new work quickly.

## Validation limits

Tests use temporary Homes, fake mail/model services, simulated clocks and injected failures. They do not exercise an actual OS suspend/resume, every real provider's failure mode, or the semantic quality of live AI judgements. No real mailbox was changed by this audit. External effects cannot generally be made transactional with a local checkpoint; possible mutations are therefore preserved for review rather than blindly replayed after a model outage.

## Validation results

- Full backend suite: **882 passed**, one skipped, 12 speed tests excluded.
- Follow-up scheduler/runtime regressions: **84 passed**; final dedicated failure-recovery and migration tests: **26 passed**.
- Frontend checks: type, boundary and hardcoding checks plus **19 unit tests** passed.
- Focused browser checks: **5 passed**, including Today recovery-command selection and a failed retry followed by a successful retry.
- Targeted Ruff, backend mypy (115 source files) and diff whitespace checks passed.

The full backend run began before the final partial-mutation guard, Stop-control race correction and Today Retry wiring were added. Those final changes were verified by the follow-up tests and browser checks listed above.
