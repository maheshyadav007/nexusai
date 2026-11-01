# NexusAI Frontend Feature Spec

## 1. Product Vision

NexusAI is an AI-first personal work OS for email, reminders, tasks, calendar, enterprise issues, documents, and internal work systems.

The product is not only a chatbot. Chat is one interface into a larger agentic workspace where the system classifies emails, understands commitments, prepares drafts, creates reminders, tracks issues, shows sources, and keeps the user focused on the next meaningful action.

The current prototype is frontend-only. All data, streaming, notifications, classification, indexing, reminders, agent behavior, sources, and tool activity are mocked in the browser.

## 2. Core Product Principles

- AI-first: every feature should eventually be reachable through natural language.
- Email-first: the core object is classified email and its relationship to work entities.
- Source-grounded: answers must expose the emails, issues, calendar items, or records behind them.
- Panel-capable: dashboards and work modules should share a reusable panel/card shell.
- Personal OS: the system should learn user preferences, writing style, approval boundaries, interruption rules, and ignored patterns.
- Useful state over telemetry: show deadlines, commitments, blockers, drafts, reminders, and action lanes instead of raw classifier metrics.
- UI-only prototype: do not add backend, database, auth, or real API dependencies in this app until explicitly requested.

## 3. Current Frontend Stack

These packages are currently present in `package.json` and should be treated as the active stack.

Runtime:

- `next`: Next.js App Router.
- `react` and `react-dom`: React UI.
- `typescript`: type system.
- `tailwindcss`, `postcss`, `autoprefixer`: styling pipeline.
- `zustand`: client-side mock UI state.
- `framer-motion`: current animation library.
- `lucide-react`: icons.
- `react-markdown`: AI response markdown rendering.
- `@radix-ui/react-slot`: slot primitive used by local UI components.
- `class-variance-authority`, `clsx`, `tailwind-merge`: local component variant and class composition utilities.

Scripts:

- `npm run dev`: start local Next dev server.
- `npm run build`: production build.
- `npm run typecheck`: TypeScript check.
- `npm run start`: run built app.

## 4. Target Frontend Architecture

These are the intended frontend decisions as the prototype matures. They should be adopted deliberately, not assumed already installed.

- Framework: Next.js, React, TypeScript.
- Styling: Tailwind CSS, CSS variables, semantic design tokens.
- Design system: NexusAI-owned component primitives. The repo may contain shadcn-style local components, but the product should not depend on shadcn as an external design system.
- Radix UI: target primitive layer for dialog, popover, tooltip, dropdown, context menu, tabs, select, and accordion.
- Animation: Motion.dev is the preferred future animation package. Current code uses `framer-motion`; migrate only when useful and avoid keeping both long-term.
- Client state: Zustand for selected category, selected email, panels, notices, reminders, theme, mode, active chat, and mock UI state.
- Server state: TanStack Query should be introduced only when real or mocked API boundaries exist. Use it for emails, tasks, calendar, reminders, panel data, and search results.
- Streaming: future frontend should consume Server-Sent Events for agent steps, chat tokens, notifications, and live panel refresh.
- Notifications: current app has a custom notification center. Sonner can replace or supplement this later for toast ergonomics.
- Desktop layer: Tauri v2 is a future packaging layer for desktop, tray, local notifications, native file access, and OS integration. It is not part of the current web-only prototype.

## 5. Theme System

The UI is theme-first. Components must use semantic tokens instead of hardcoded colors.

Current themes:

- `editorial`: default Hallmark-inspired light theme with paper surfaces, sharp rules, and sparse coral accent.
- `terminal`: dark console-like system theme.
- `mintlify`: clean AI-docs style.
- `linear`: strict dark product UI.
- `nexus`: deep AI workspace theme.
- `graphite`: neutral enterprise theme.

Mode support:

- Light mode.
- Dark mode.

Theme tokens control:

- Canvas and elevated surfaces.
- Card surfaces.
- Text hierarchy.
- Accent color.
- Hairline borders.
- Status colors.
- Radius.
- Shadows.
- Typography.
- Spacing.
- Glass opacity.

Future theme candidates:

- Professional.
- Midnight.
- Glass.
- Nord.
- Samsung enterprise.

## 6. Application Layout

The main app shell has three persistent work areas:

- Header: logo, primary navigation, current context, next best action, and live sync/classification/indexing activity.
- Left classification container: email categories, counts, unread pressure, priority inbox, and custom routing rules.
- Center workspace: Home canvas, Emails, Reminders, Calendar, Tasks, Panels, Search, or Settings.
- Right chat rail: Perplexity-style indexed-email chatbot with answer, sources, actions, and composer.

Desktop-first behavior:

- Left and right rails stay visible on desktop.
- Center workspace scrolls independently.
- Responsive behavior should collapse rails or stack sections on smaller screens without losing primary actions.

## 7. Header

Purpose: show brand, current operating state, and a lightweight sense that the system is alive.

Header content:

- NexusAI logo.
- Product label: personal work OS.
- Primary nav: `Home`, `Emails`.
- Current route context, for example `Operating picture` or `Classified inbox`.
- Next best action, for example supplier risk reply before 2 PM.
- Priority unread count.
- Guarded/privacy state.
- Live activity sequence: `Email fetching` -> `Classification` -> `Indexing`.

Header flows:

- `Home` opens the operating canvas.
- `Emails` opens the classified inbox and resets to all indexed mail.
- Activity icons animate between pipeline stages.
- Header must not include a global search bar. Search belongs in the Search page or local page filters.

## 8. Left Classification Container

Purpose: this is the email routing map. The user should understand where work is going and why.

Default category groups:

- Smart views:
  - Priority inbox.
  - Needs action.
  - All indexed mail.
- Source views:
  - Executive signal.
  - Customer commitments.
  - PLM / release blockers.
  - GitHub + swarm.
- Personal:
  - Watchlist.

Each category shows:

- Icon.
- Name.
- Description.
- Total count.
- Unread count.
- Active indicator.

Priority inbox behavior:

- Priority inbox is a computed cross-category view.
- It should include emails that matter now based on priority, unread state, urgency, sender importance, deadlines, blockers, or risk.
- It is not a folder and should not duplicate category ownership.

Custom category flow:

- User clicks `+` or `Create routing rule`.
- UI creates a custom signal category.
- Full v1 should allow name, icon, color, rule conditions, AI semantic instructions, source scope, preview matches, and save/cancel.

Rule cases:

- Sender/domain: route all emails from a VP, customer, or system.
- Keyword: route messages containing "blocker", "renewal", "decision needed", or "security review".
- Entity: route PLM IDs, GitHub PRs, customer names, files, systems, and projects.
- Deadline: route "today", "EOD", "before 2 PM", or time-sensitive messages.
- AI intent: route messages that sound like asks, commitments, risks, decisions, or follow-ups.
- Negative rule: ignore FYI digests unless the user is mentioned.

## 9. Home Operating Canvas

Purpose: the Home page should answer "what should I do now?" without forcing the user to inspect every inbox or system.

Current modules:

- AI live brief with delete-and-type refresh animation.
- Attention lanes: `Now`, `Next`, `Waiting`, `Ignore`.
- Priority focus: priority inbox count and unread priority count.
- Timeline pressure: deadlines, meetings, reminders, and issue gates in one day spine.
- Commitment ledger: promises extracted from emails, issues, and meetings.
- Personal memory: writing style, work rhythm, escalation rules, approval boundaries.
- Agent queue: drafts, reminders, pings, prep briefs, and follow-ups waiting for approval.

Canvas controls:

- `Edit canvas`: shows edit controls.
- `Restore card`: restores a hidden module.
- Hide/delete card while editing.
- Future: drag, resize, reorder, pin, duplicate, configure source, configure refresh interval.

Expected flow:

- User lands on Home.
- NexusAI highlights the highest leverage next action.
- User opens the classified inbox, approves agent work, creates reminders, or asks chat for explanation.
- User customizes the canvas into a personal dashboard.

## 10. Panel System

Purpose: panels are reusable work surfaces for email, calendar, reminders, issues, chat, trading, files, and enterprise systems.

Panel shell:

- Title.
- Category/source.
- Priority badge.
- Content area.
- Last updated timestamp.
- Settings action.
- Delete action.
- More actions menu.

Default panels:

- Important emails.
- Upcoming meetings.
- PLM issues.
- GitHub / swarm issues.
- Reminders.
- Draft emails.
- Follow-ups.

Panel flows:

- Add panel from templates.
- Remove panel.
- Configure title, source, filters, refresh frequency, sort order, priority rules, and visibility.
- Open panel item and filter the relevant workspace.
- Agent-generated panel: user asks chat to "add a PLM dashboard"; UI creates a new PLM panel.

Panel design rule:

- Home can use panels, but it should not become cluttered. Prefer strong information hierarchy and a few high-value modules.

## 11. Emails Page

Purpose: a Gmail-like classified inbox with AI summaries, source metadata, routing explanation, and direct actions.

Top summary:

- Selected category name.
- Category description.
- Priority inbox count.
- Emails shown.
- Unread count.

Local controls:

- Search classified email.
- Filters.
- Explain routing.

Search behavior:

- Filter by sender, sender role, subject, summary, key info, entities, source, rule matches, suggested action, sentiment, and category.
- Search should apply to the current category by default.
- Search should be able to expand to all indexed mail.

Filter behavior:

- Read/unread.
- Priority.
- Source system.
- Classification mode: Rule, AI, Hybrid.
- Confidence range.
- Sentiment.
- Entity.
- Indexed freshness.
- Date/time.
- Has reminder.
- Has draft.
- Needs action.

Empty states:

- No email in category.
- No result for search.
- No match for filters.
- Index still syncing.

## 12. Email Card

Purpose: convert an email thread into a decision-ready object.

Visible fields:

- Read/unread marker.
- Sender.
- Sender role.
- Subject.
- Received time.
- Indexed time.
- Priority badge.
- Read/unread badge.
- AI summary.
- Key info bullets.
- Source badge.
- Classification mode badge.
- Extracted entities.

Buttons:

- `Open`: select/open detail view.
- `Mark read` / `Mark unread`: toggle read state.
- `Remind me`: create entity-linked reminder from the email.
- `Reclassify similar`: teach classifier and route similar emails.
- `Draft reply`: prepare a mocked AI reply.

Email detail view required for v1:

- Full thread.
- AI summary.
- Action items.
- Deadlines.
- Owners.
- Key info.
- Attachments/files.
- Source metadata.
- Classification explanation.
- Related reminders, tasks, calendar events, issues, and chat answers.
- Controls for draft reply, create reminder, create task, reclassify, copy summary, open source.

## 13. Classification Feedback

Purpose: user corrections should improve routing for this email and future similar emails.

Reclassification event fields:

- Email ID.
- Email subject.
- From category.
- To category.
- Trigger: manual, email, chat.
- Reason.
- Status: queued or applied.
- Time.

Correction sources:

- Email card.
- Email detail panel.
- Chat action.
- Follow-up row.
- Bulk selected emails.

Expected flow:

- User says the email is misclassified.
- UI asks or infers the correct category.
- UI previews similar emails affected.
- User confirms.
- Current email moves category.
- Similar pattern is recorded.
- Feedback log updates.
- Notification confirms classifier update.
- Chat can explain the new rule.

Example corrections:

- Stuck swarm jobs should become Needs action.
- FYI release notes should move to Ignore unless user is mentioned.
- Customer renewal threads should route to Customer commitments.
- Ownerless PLM blockers should create reminders.

## 14. Right Chat Rail

Purpose: a Perplexity-like answer rail for asking about indexed email and work context without leaving the current workspace.

Chat header:

- Title: Ask indexed email.
- Subtitle: answers with context.
- Status badge: thinking, streaming, ready, answered.

User query card:

- Query text.
- Timestamp.
- Copy button.
- Retry button.
- Branch indicator.
- Future edit button.

AI response:

- Markdown answer.
- Simulated streaming.
- Skeleton loading.
- Structured response blocks.
- Compact source button, for example `5+ sources`.
- Copy, like, dislike, retry.
- Create reminder.
- Teach classifier.
- Follow-up rows with arrow.
- Bottom composer.

Required response blocks:

- Markdown.
- Tables.
- Metrics.
- Status cards.
- Timelines.
- Task lists.
- Email cards.
- Source/citation rows.
- Tool activity cards.
- Agent execution timeline.

Required v1 commands:

- Summarize important unread emails.
- Show action items due today.
- Draft a reply to selected email.
- Create reminder from selected email.
- Create reminder from chat answer.
- Explain why an email was classified.
- Reclassify this email.
- Reclassify similar emails.
- Search by person, company, topic, deadline, entity, or source.
- Show sources for an answer.
- Add a panel to Home or Panels page.

## 15. Source And Citation System

Purpose: every AI answer should be traceable to actual email/work sources.

Source row fields:

- Title.
- Origin/source system.
- Snippet.
- Confidence.
- Timestamp.
- Entity type.
- Source ID.

Source behavior:

- Sources appear as compact rows or a `5+ sources` button.
- Clicking source count opens a source drawer/view.
- Clicking an email source opens Emails with that email selected.
- Clicking an issue source opens the issue panel or filtered Panels view.
- Clicking calendar source opens Calendar with that event highlighted.
- Clicking task/reminder source opens its page with the item selected.
- If multiple sources are present, the center workspace can become a filtered source result view.

Search/source relationship:

- Search results and answer sources should share the same source card model.
- If sources are present inside search results, clicking them should filter the visible workspace.

## 16. Agent Execution UI

Purpose: make AI work observable without exposing noisy internals.

Agent timeline steps:

- Understanding request.
- Searching emails.
- Checking calendar.
- Searching enterprise systems.
- Creating draft or reminder.
- Final answer.

Tool activity card fields:

- Tool name.
- Input summary.
- Output summary.
- Status: running, success, failed, pending.
- Duration.

Streaming events:

- Planning.
- Searching emails.
- Searching calendar.
- Searching PLM/issues.
- Generating response.
- Waiting for approval.
- Completed.

UI rule:

- Show tool activity when it builds trust or explains latency. Do not flood the main Home screen with raw pipeline blocks.

## 17. Reminders

Purpose: reminders are entity-linked memory. They can be created by the user, chat, email cards, issues, calendar events, or agents.

Reminder fields:

- Title.
- Due time.
- Countdown.
- Status: due, upcoming, scheduled, complete.
- Owner: You or NexusAI.
- Trigger: manual, chat, email, agent.
- Entity type: email, chat, issue, calendar, manual.
- Entity title.
- Source ID.
- Note.

Reminder card shows:

- Status badge.
- Owner.
- Trigger badge.
- Title.
- Linked entity.
- Due time.
- Countdown.
- Note.
- Snooze.
- Complete.

Creation flows:

- Manual from Reminders page.
- Email card via `Remind me`.
- Chat via `Create reminder`.
- Agent queue via approval.
- Future: calendar event, issue, search result, source row.

Required future flows:

- Recurring reminders.
- Reminder rules.
- Notification preferences.
- Snooze presets.
- Complete with note.
- Open linked entity.

## 18. Notifications

Purpose: notify the user about important work events without interrupting the workspace.

Current UI:

- Custom top-right notification center.
- Animated toast entries.
- Dismiss button.

Notification fields:

- Title.
- Description.
- Tone: success, warning, info, danger.
- Time.

Notification types:

- Reminder fired.
- Reminder created.
- Email classified.
- Classifier updated.
- Draft ready.
- Calendar conflict detected.
- Agent finished.
- Approval required.
- New important email.
- System event.

Target:

- Sonner may be introduced for toast behavior.
- Notification center should remain a product surface for history, unread notices, and linked actions.

## 19. Tasks

Purpose: combine inferred work and explicit work into a consequence-ranked task list.

Summary cards:

- Critical.
- High.
- Delegated.
- AI prepared.

Action table fields:

- Action.
- Owner.
- Due.
- Source.
- Priority.

Required flows:

- Filter by owner, priority, source, due time, status.
- Group by owner/source/date.
- Complete.
- Delegate.
- Snooze.
- Create reminder.
- Ask chat about task.
- Open source entity.

## 20. Calendar

Purpose: show meetings with connected email, task, reminder, draft, and issue context.

Calendar alert:

- Conflict title.
- Suggested action.
- Priority badge.

Calendar card fields:

- Meeting title.
- Time.
- Attendees.
- Location or meeting link.
- Status: confirmed, conflict, tentative.

Required flows:

- Open meeting context.
- Show linked emails, issues, tasks, reminders, and drafts.
- Ask chat to prepare meeting brief.
- Create reminder.
- Resolve conflict.
- Schedule new meeting.

## 21. Search

Purpose: universal search across email, calendar, tasks, reminders, panels, files, PLM, GitHub, swarm, and future enterprise data.

Result card fields:

- Icon.
- Title.
- Source path.
- Excerpt.
- AI relevance indicator.
- Sources if available.

Search behavior:

- Query subject, summary, sender, entities, source systems, issue IDs, meeting titles, reminders, tasks, and panels.
- Filter by source type, date, priority, owner, read/unread, category, status.
- Group by source type where useful.
- Clicking a result opens or filters the relevant page.
- If a result has multiple supporting sources, open source view first.

Examples:

- `supplier risk`: email thread, calendar meeting, action item, file source.
- `PLM-1842`: issue context and related email.
- `Maya decision today`: sender thread and reminders.

## 22. Settings

Purpose: configure the workspace feel and future system behavior.

Current settings:

- Theme selection.
- Light/dark mode.
- Mode-aware surfaces.
- Enterprise privacy labels.
- Glass density.
- Experimental accent mixing.

Required future settings:

- Connectors.
- Privacy boundaries.
- Memory controls.
- Notification rules.
- Classification rules.
- Agent approval rules.
- Default writing style.
- Source visibility.
- Theme/radius/shadow density.
- Desktop notification preferences.

## 23. Command Palette

Purpose: one fast entry point for navigation, search, actions, and AI commands.

Shortcut:

- `Cmd+K`.
- `Ctrl+K`.

Required capabilities:

- Navigate pages.
- Search indexed data.
- Run actions.
- Ask AI.
- Create reminder.
- Add panel.
- Reclassify selected email.
- Draft reply.
- Toggle theme.
- Open settings.

Implementation target:

- Radix Dialog or Command-style custom primitive.
- Motion.dev transition.
- Keyboard-first navigation.
- Recent commands.
- Context-aware actions based on selected email/category/page.

## 24. Data Model For Frontend

Core frontend objects:

- `EmailCategory`: id, name, description, color, count, unread, rule count, AI count, custom flag.
- `ClassifiedEmail`: sender, role, subject, summary, priority, source, category, read state, confidence, classification mode, rule matches, key info, entities, indexed time, sentiment.
- `Reminder`: title, due time, countdown, status, owner, trigger, entity type, entity title, source ID, note.
- `ReclassificationEvent`: email, from category, to category, trigger, reason, status, time.
- `CalendarEvent`: title, time, attendees, location, status.
- `ActionItem`: task, owner, due, source, priority.
- `Panel`: title, category, priority, items, last updated.
- `SourceCard`: title, origin, snippet, confidence.
- `ToolRun`: name, input, output, status, duration.
- `ToastNotice`: title, description, tone, time.

Future frontend API contracts:

- `EmailThread`.
- `EmailDraft`.
- `ReminderRule`.
- `ReminderInstance`.
- `Notification`.
- `AgentEvent`.
- `PanelConfig`.
- `SearchResult`.
- `SourceReference`.
- `UserMemory`.
- `ConnectorStatus`.

## 25. Server Boundary Assumptions

This frontend should be able to connect later to a backend without changing the product model.

Expected backend boundary:

- REST or RPC for normal CRUD.
- SSE for streaming agent/chat/notification events.
- TanStack Query for server-state caching and invalidation.
- Repository/service abstraction belongs on the backend, not inside this UI prototype.

Expected backend-backed features later:

- Email ingestion.
- Threading.
- Summarization.
- Draft generation.
- Calendar APIs.
- Reminder rules and scheduler.
- Notification events.
- SQLite/PostgreSQL persistence.
- Hybrid search.
- LangChain or equivalent agent runtime.
- MCP/integration tools for PLM, Swarm, GitHub, JIRA, Confluence, trading, and internal systems.

## 26. Minimum Usable V1

The first genuinely usable version should include:

- Category router with default and custom categories.
- Rule-based and AI-based classification explanation.
- Computed priority inbox.
- Classified email cards with summary, metadata, read/unread, source, priority, and actions.
- Email detail view.
- Local search and filtering inside Emails.
- Universal search with source-aware navigation.
- Perplexity-style chat with markdown, streaming, sources, branching, retry, copy, feedback, and follow-ups.
- Source drilldown that opens or filters the center workspace.
- Entity-linked reminders from email, chat, calendar, issue, and manual input.
- Classifier feedback and similar-email reclassification.
- Home operating canvas with attention lanes, timeline pressure, commitment ledger, personal memory, and agent queue.
- Panel dashboard with add/delete/configure.
- Task table generated from emails, reminders, meetings, and issues.
- Calendar conflict and meeting-context view.
- Notification center and toast feedback.
- Theme settings and light/dark mode.
- Command palette.

## 27. Prototype Non-Goals

Do not add these unless explicitly requested:

- Backend server.
- Real APIs.
- Database.
- Authentication.
- Real email sending.
- Real model calls.
- Persistent storage beyond client state.
- Tauri packaging.
- Production scheduler.

## 28. Design Rules

- Keep the UI premium, mature, and enterprise-grade.
- Avoid childish glass, excessive gradients, and decorative noise.
- Prefer useful extracted work state over raw metrics.
- Use semantic tokens, not hardcoded component colors.
- Keep motion subtle, fast, and meaningful.
- Make sources visible and actionable.
- Make feedback loops obvious.
- Make reminders entity-linked.
- Make chat feel like a command surface over the whole OS, not a separate toy.
