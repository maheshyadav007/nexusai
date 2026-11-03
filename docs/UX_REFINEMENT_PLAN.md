# Workspace UX refinement

Planned 2026-11-03. Builds on the AI generation feedback work; keeps its distinction between system preparation and model activity.

## Changes

- Planner: quiet rows and fine separators; expand details in place; compact quick-add forms; immediate, reversible task completion with rollback on failure. Reminders keep time and recurrence easy to scan.
- Settings: a distinct navigation rail, vertical divider, clearer current item, independent scrolling in the modal, motion through shared primitives.
- Connectors: an overview of Email and MCP connections. Email opens its account settings and archive import. MCP opens its own servers and tools. Configuration appears only after choosing a connection.
- Cockpit: a brief status overview, attention and active work first, upcoming runs alongside, then a short activity feed. Detailed system health and maintenance stay behind disclosures. Mail sync is not duplicated as an agent job.
- Chat: minimized pill, attached right panel, full central page. Floating geometry remains behind a disabled flag for future use. Reading an email or opening a document minimizes the side panel. Explicitly reopening it works while reading. Plus means New chat. Full page offers return-to-panel and minimize controls.
- Managed agent histories: visible protection notice; no arbitrary chat messages, retries, version changes, manual compaction, renaming, archiving or context edits. Explicit questions and approvals remain available. Server enforcement matches the UI.

## Related known issues

Check and fix the brief omitting pending decisions, agent rows attributing shared-chat runs incorrectly, and hourly defaults for new Homes. Do not do bulk mailbox cleanup, change credentials, or expand the feature roadmap as part of this work.

## Verification

Run frontend types, theme, boundary and hardcoding checks; backend checks and focused protection/brief/registry tests. Exercise planner, connection navigation, chat view transitions and protected question/approval flows with a temporary Home and fake model. Review screenshots before rebuilding and restarting the local app.
