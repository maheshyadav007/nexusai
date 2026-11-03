# Workspace UX refinement

Planned 2026-11-03. Builds on the AI generation feedback work; keeps its distinction between system preparation and model activity.

## Changes

- Planner: quiet rows and fine separators; expand details in place; compact quick-add forms; immediate, reversible task completion with rollback on failure. Reminders keep time and recurrence easy to scan.
- Settings: horizontal dividers between navigation groups, clearer current item, independent scrolling in the modal, motion through shared primitives.
- Connectors: an overview of Email and MCP connections. Email opens its account settings and archive import. MCP opens its own servers and tools. Configuration appears only after choosing a connection.
- Cockpit: a brief status overview, attention and active work first, upcoming runs alongside, then a short activity feed. Detailed system health and maintenance stay behind disclosures. Mail sync is not duplicated as an agent job.
- Chat: minimized pill, attached right panel, full central page. Floating geometry remains behind a disabled flag for future use. Reading an email or opening a document minimizes the side panel. Explicitly reopening it works while reading. Plus means New chat. Full page offers return-to-panel and minimize controls.
- Managed agent histories: visible protection notice; no arbitrary chat messages, retries, version changes, manual compaction, renaming, archiving or context edits. Explicit questions and approvals remain available. Server enforcement matches the UI.

## Related known issues

Check and fix the brief omitting pending decisions, agent rows attributing shared-chat runs incorrectly, and hourly defaults for new Homes. Do not do bulk mailbox cleanup, change credentials, or expand the feature roadmap as part of this work.

## Verification

Run frontend types, theme, boundary and hardcoding checks; backend checks and focused protection/brief/registry tests. Exercise planner, connection navigation, chat view transitions and protected question/approval flows with a temporary Home and fake model. Review screenshots before rebuilding and restarting the local app.

## Completed verification

- Frontend type, theme, hardcoding and boundary checks passed; 19 unit tests passed.
- Backend formatting, lint, types and dependency boundaries passed. Full regression run: 773 passed, 1 skipped; one legacy connector test still sent a manual message into the now-protected Mail chat. Updated it to dispatch an internal Mail run and verified it passes. Nine managed-chat tests also pass, including explicit questions and approvals.
- Isolated Home with a fake model: checked Settings horizontal group dividers, Email connection drill-in, quiet task rows and completion, attached/full chat and draft preservation, New chat reset, email-click minimization (including the selected email), explicit reopening while reading, protected Mail chat, and Cockpit at full and narrowed widths.
- Pending brief and Inbox review fixes remain marked for confirmation on real scheduled runs. The default hourly schedule already worked; a new-Home regression test now covers it.

## Follow-up refinements, 2026-11-04

- Managed chats now show a grey, locked composer and a short warning. Still proceed explicitly unlocks new messages for that chat in the current browser session; Lock input reverses this. Each request carries acknowledgement. Retry/version changes and other history-editing controls remain protected. Questions and approvals stay available.
- Session rows and agent conversation actions open the right panel. Ordinary deep links resolve there too. Full page is entered through the panel’s expand control and preserves the current conversation/draft. The panel grew from 440 px to 480 px, capped at the viewport width. Today now also stacks its columns when the panel leaves less room.
- Documents uses one aligned file list with search, a folder filter and a separate folder-management dialog. File metadata sits below each name.
- Finished email summaries and morning briefs retain a thin static AI-colored outline with an inset title; generation keeps its separate animation.
- Verified the locked/acknowledged composer, panel/full transitions, deep-link entry, Documents and folder dialog, summary styling in an isolated Home. 66 chat/backend regression tests and 19 frontend unit tests passed, along with frontend types, theme, boundaries and hardcoding checks.
