# Email management implementation

Scope: the 4 November email-agent audit and subsequent feedback clarification. Keep `Today`; use recorded names elsewhere. Space Grotesk headings/navigation, Inter reading text. Pets excluded. Existing approval boundaries remain authoritative. No model-weight training or bandit optimization.

## Checklist

- [ ] Atomic dispatch/trigger registration, restart and race regression coverage
- [ ] Bounded burst claiming without dropped trigger coverage
- [ ] Overdue notification separate from completion
- [ ] Brief readiness independent of optional history/interview
- [ ] Freshness fences for human corrections and newer incoming mail
- [ ] Successful-outcome digest/review watermarks and catch-up
- [ ] Complete, versioned brief artifacts and artifact-specific feedback/freshness UI
- [ ] Purpose-aware shared context for triage, draft, brief and chat
- [ ] Scoped feedback observations, explicit preference proposals, conflict/expiry/undo
- [ ] Preference versions, preview, restore and inspectable run context
- [ ] Typed handoffs, per-run message budgets and accountable ownership
- [ ] Queue priority/aging, pause/cancel provenance, timezone-aware scheduling
- [ ] Accurate behavior signals with actor/account scope
- [ ] Prompt uncertainty/evidence/commitment improvements
- [ ] Held-out temporal eval fixtures and deterministic end-state checks
- [ ] Agreed copy and font changes
- [ ] Browser verification in both themes and responsive layouts
- [ ] Appropriate backend/frontend checks, production build and healthy running app

Live-model quality is measured separately from deterministic correctness. Do not claim a live mailbox evaluation from synthetic model tests. Record implementation evidence and remaining limitations here as work proceeds.
