# Agent context and prompt audit

Audited on 2026-11-06 against the consolidated mail organization flow. This describes execution paths, including several modes of the same Mail agent; it does not imply thirteen independent model agents.

## What each run receives

All runtime agents receive the system rules, their job prompt, the person's profile and fresh personal prompt files, applicable approved preferences, and bounded relevant memory. Mail evidence, inferred facts, tool output and conversation summaries are treated as data. Explicit approved preferences take precedence over inferred habits; category descriptions define matching and cannot authorize actions.

| Execution path | Additional context and constraints |
| --- | --- |
| Individual Mail judgement | Current conversation evidence, work board, corrections, Smart descriptions and Exact rules/descriptions. Actual message sender identities select sender preferences. Exact matches and explicit user decisions remain authoritative. Importance, Priority inclusion and Starred are separate concepts. |
| Grouped learning after bulk arrival | Account, supplied group IDs, sender identities, representative samples, counted sender signals, existing category settings and account-scoped learned notes. Only supplied groups can be recorded, with complete coverage. Proposed folders await confirmation. Known groups are reused. |
| Historical filing | Dedicated filing instruction and existing folder settings. Cannot overwrite importance/status, create work, learn facts or suggest categories through its recorded result. |
| Interview | Current account's unresolved learning, existing personal instructions, source sender identities and at most three targeted questions. Narrow tools permit reading evidence and applying approved learning answers; files, commands, sending, tasks, folders and agent creation are unavailable. All interviews require review for personal prompt changes, including manually started interviews. |
| Hourly digest | Completed judgements, account/source threads and current work board. Does not rejudge mail. Existing work prevents repeated proposals. |
| Inbox review | Current review evidence, personalized settings and work board. Uses the same guarded runtime and evidence boundaries. |
| Morning brief | Obligations snapshot, applicable source thread preferences, brief wishes and coverage limits. Proposed work is distinguished from accepted commitments. |
| Custom event runs | Event evidence is bounded as external data; source threads/account are saved with the run. Different mailbox accounts are not combined in one source batch. |
| Scheduled runs | Saved schedule instructions, context profile and timezone; runtime clock identifies the timezone. Relevant obligation source threads accompany built-in scheduled work. |
| Interactive assistant | Person's request, selected conversation history and explicitly attached context. Attached context survives recovery without a graph checkpoint. |
| Direct reply draft | Current conversation, actual sender-scoped preferences, writing samples, signature and explicit current-time/on-demand drafting instruction. Unsupported dates or decisions must remain placeholders. |
| Conversation summary / compaction | Mail or earlier conversation is evidence. Generated summaries remain untrusted when reused; compaction preserves the current request and all its tool results. |

Category tools expose and update mode, personalized description, sender rule and literal subject prefix. Starter PLM/Swarm folders use Exact subject prefixes with Priority off. User-authored personal prompts are preserved rather than overwritten with new defaults.

## Gaps corrected

- Replaced conflicting interview and historical-learning instructions with the new targeted interview and filing-only behavior. Removed instructions to infer importance from ignored mail and to delete empty categories automatically.
- Scoped sender preferences to actual source identities. Mentioning a sender inside a body, or using an address containing another address, cannot activate that sender's preference.
- Scoped learned group notes and sender examples to the source account. Identical notes from different accounts retain separate provenance.
- Escaped injected `untrusted` boundary tags in external evidence, tool output, inferred notes, attachments and reused summaries. Summary messages do not become trusted system instructions.
- Preserved current tasks and tool results during compaction, message metadata during task injection, and attached evidence during restart recovery. Run metadata cannot override validated context-profile settings.
- Fingerprinted explicit category/personal settings before mail decisions. Changed settings discard and requeue stale results; explicit retries refresh instructions while preserving the original evidence-version check.
- Refused background tools when the selected mailbox no longer matches the run's saved account, avoiding actions against a different account.
- Classified oversized model input and malformed tool arguments as terminal input/response failures rather than transient outages that retry forever.
- Prevented a single automatically extracted obligation from being proposed as both a task and a reminder.

## Verification and limits

Regression tests use temporary Homes and fake model/mail services. They cover source scoping, prompt boundaries, interview capabilities, historical restrictions, stale settings, compaction, recovery, duplicate work, timezone context, context overflow and invalid tool arguments. No real mailbox was modified by this audit.

Validation: the full backend run produced **904 passed**, one skipped and 12 speed tests excluded, with two failures subsequently corrected: an exact safety-phrase assertion and an older expectation that duplicate note text discarded its second source. The final targeted run passed **52 tests**, including both failed checks, all new context regressions, direct-summary error handling and preference previews. The full run preceded the final interview/recovery/summary additions; those are covered by the targeted run. Ruff, formatting, mypy (116 source files) and diff whitespace checks passed. No frontend code changed in this context audit.

These checks verify context construction and deterministic safeguards. They do not establish live-model judgement quality, resistance to every prompt-injection attempt, or fit within every provider's context window. Oversized requests fail visibly instead of silently deleting the person's instructions. Existing user-authored prompts may still express earlier choices, intentionally retaining the person's authority.

See [timing and recovery](AGENT_TIMING_AND_RECOVERY.md) for trigger conditions and replay policy, and [implementation notes](MAIL_ORGANIZATION_IMPLEMENTATION.md) for the underlying mail organization flow.
