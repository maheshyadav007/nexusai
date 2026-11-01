---
version: alpha
name: NexusAI Editorial
description: "A Hallmark Editorial-inspired personal work OS for AI email classification, editable work canvas cards, and indexed-email chat. The interface is light-first, warm, sharp, and premium: paper-toned surfaces, hairline rules, scarce coral accent, square editorial cards, and a right-side Perplexity-style answer rail."

themes:
  default: editorial
  available:
    - terminal
    - editorial
    - mintlify
    - linear
    - nexus
    - graphite

colors:
  canvas: "rgb(var(--canvas))"
  canvas-elevated: "rgb(var(--canvas-elevated))"
  surface-1: "rgb(var(--surface-1))"
  surface-2: "rgb(var(--surface-2))"
  surface-3: "rgb(var(--surface-3))"
  ink: "rgb(var(--ink))"
  ink-muted: "rgb(var(--ink-muted))"
  ink-subtle: "rgb(var(--ink-subtle))"
  accent: "rgb(var(--accent))"
  hairline: "rgb(var(--hairline))"

typography:
  display: "Inter Tight, 800, letter spacing 0"
  body: "Inter, semantic text tokens"
  serif-accent: "Playfair Display italic, used sparingly"

layout:
  header: "Elegant NexusAI masthead with Home/Emails navigation, current operating context, next best action, guarded state, and compact Email fetching -> Classification -> Indexing activity line. No global search."
  left: "Attention router with a focus queue, grouped smart views, source views, personal views, counts, unread pressure, and routing-rule creation."
  home: "AI operating picture with attention lanes, timeline pressure, commitment ledger, personal memory, and agent queue."
  emails: "Gmail-like classified email cards with summary, key info, metadata, read/unread state, and category filtering."
  right: "Full-height indexed-email chat with user query, markdown answer, compact 5+ sources button, row-style follow-ups, actions, and bottom composer."
  reminders: "Entity-linked reminder queue triggered by email cards, chat answers, manual entry, or agent actions."
  feedback: "Classifier feedback loop where inbox or chat corrections can reclassify the current email and similar future patterns."

principles:
  - "Show useful work state, not internal classifier telemetry."
  - "Keep category navigation clean and readable."
  - "Use semantic CSS tokens rather than component-level color constants."
  - "Make AI feel alive through subtle text streaming and in-place brief edits."
  - "Prioritize extracted commitments, timing pressure, and agent-ready actions over generic dashboards."
  - "Expose personal memory as an editable product surface, not hidden magic."
  - "Let any meaningful entity become a reminder: email, chat answer, issue, meeting, or manual note."
  - "Treat user feedback as training signal: corrections should reclassify this email and similar future emails."
  - "Favor hairline structure over decorative glass or heavy gradients."
---

## Product Intent

NexusAI is an AI-first personal work OS focused on email classification and indexed work intelligence. It routes email into user and system categories, summarizes the important messages, maintains editable work cards, and lets the user chat with their indexed email and enterprise context.

## Current UI Direction

The active direction is Hallmark Editorial, adapted for an enterprise AI app. It uses light mode by default, warm paper surfaces, square cards, thin rules, sparse coral accent, and dense but calm information layout.

Hallmark Terminal remains available as a dark alternative when the product should feel like an AI work system, command center, or indexed-memory console.

The home screen is intentionally reduced:

- Top nav: Home and Emails.
- Left rail: attention router with focus queue, smart views, source views, personal watchlists, unread pressure, and routing-rule creation.
- Home: operating picture with a top AI brief, attention lanes, timeline pressure, commitment ledger, personal memory, and agent queue.
- Emails: category-filtered Gmail-like cards with summaries, key info, metadata, and read/unread controls.
- Right rail: Perplexity-style chat with the user query, streamed markdown response, compact source button, branch indicator, copy, retry, like, dislike, follow-up rows, and bottom input.
- Reminders: queue supports manual reminders plus reminders created from email cards, chat answers, and agent actions.
- Feedback: users can correct classification from email cards or chat; the UI records the correction and applies a mock reclassification pattern.

## Motion

Motion should be useful and restrained:

- Header activity line gently advances through the work stages.
- The chat answer streams chunk by chunk.
- AI brief text erases backward character by character, then types the refreshed sentence.
- Cards use simple hover and focus transitions only.

## What Not To Show On The Home Screen

Do not surface raw classifier counters, live pipeline internals, rule stacks, connector freshness, or confidence telemetry as hero content. Those details can exist in settings or inspection flows, but the primary workspace should answer: what needs attention, what changed, and what should I do next?

## Product Surfaces To Keep Exploring

The strongest value is not another inbox. It is the personal layer that sits above inboxes:

- Attention lanes: Now, Next, Waiting, Ignore.
- Commitment ledger: promises extracted from email, issues, and meetings.
- Timeline pressure: deadlines, meetings, reminders, and issue gates in one day spine.
- Personal memory: writing style, interruption rules, stakeholder preferences, approval boundaries.
- Agent queue: drafts, reminders, owner pings, prep briefs, and follow-ups waiting for approval.
- Ignore model: explicit reasons why something is muted or deferred.
- Entity reminders: any email, chat answer, issue, calendar item, or manual note can become a reminder with source linkage.
- Reclassification feedback: when a user corrects routing, the system should re-evaluate similar messages and explain the applied rule.
