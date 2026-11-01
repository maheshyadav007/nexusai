# NexusAI Design Direction

Status: **approved 2026-11-01** (step 0.5 in `docs/COMPONENT_PLAN.md`). Every screen follows it.

Produced with [unslop](https://github.com/heydamir/unslop) by Damir Sokolovsky ([@heydamir](https://x.com/heydamir)), CC BY 4.0, reviewed at commit `1d13095`.

## Direction

- **Product:** A local agent that reads a corporate employee's mail, files and notes and handles the routine work, with every action visible, approvable and undoable.
- **Character:** Steady, candid, a little warm.
- **World:** A well-kept desk: paper, ink and a red pencil that marks only what needs your decision.
- **Moments:** The Focus feed, showing work being handled live, and the approval card, where a draft waits for your decision.
- **Signature:** The four-segment stage bar from v9, used wherever agent work appears: feed, live pill and session list.

## Mode: polish v9, with one larger change

v9 already has character, so it keeps its identity. Only the audit findings change, plus the surface color.

**Keep:** the terracotta accent, the three-pane layout, the live pill, the Focus feed, the stage bars, the serif page headline and the plain voice ("What should I take off your plate?").

## Audit of v9

Measured on the rendered home screen, except where the source file is named.

| Area | Finding | Fix |
|---|---|---|
| Layout | The root has `min-width:1500px`, so at 1366px and 1440px the agent panel is cut off, including the Send button | Fluid layout that works from 1366px, as the quality bar requires |
| Layout | Titles truncate to "New mail from ...", "Active pull ..." and "Swarm r..." | Give titles room; move meta out of their way |
| Type | 53% of text (130 of 244 elements) is below 11px, down to 8.5px | Enforce the theme's 11px minimum |
| Type | 18 font sizes on one screen | The six sizes already in the theme |
| Type | Instrument Serif's "1" reads as "l", so "41" looks like "4l" | Numbers always use the sans or mono face |
| Type | 16 uppercase tracked labels, such as `MAIL` and `DOCUMENTS` | Sentence case |
| Color | Meta text is 3.24:1 and faint text 2.26:1 on the page, against a 4.5:1 target | Theme `ink.muted` for all meta text (5.26:1 on warm paper) |
| Color | Peach surfaces, three colored radial washes and a dot grid behind everything | Quiet surfaces, no washes |
| Color | Accent on every toggle, dot, count and status, so nothing stands out | Accent marks only what needs a decision or is running |
| Color | Connector tiles in three colors | One neutral tile style |
| Effects | 14 gradient elements on screen | Solid surfaces; a tonal step at most |
| Icons | `✦` marks every AI insight; `⚙ 👍 👎` appear in the source | Line icons from one set |
| Spacing | 67 different padding values in the source, such as `11px 13px` | Theme space steps only |
| Motion | Six continuous animations at once: aurora, breathe, spin, equalizer, sweep and pulse | Only real running work may move, and it respects reduced motion |
| Motion | 43 uses of `transition:all` in the source | Name the properties |
| Copy | "41 handled" appears at least five times | State it once |
| Copy | Developer terms: "urgency 0.91", "re-embedded", "386 chunks" | Say what happened and why it matters to the reader |
| Content | Demo data suits a software engineer (GitHub, Linear, pull requests) | Gallery data about mail, documents and meetings |
| Navigation | Live pill, view tabs and page title stack in the header | One clear level per job |

## Theme changes

Applied to `nexus-light`. `nexus-dark` follows the same rules, with its peach tints removed. Values go in theme files only.

| Token | v9 | Now |
|---|---|---|
| `color.surface.page` | `#F8EAE2` | `#F7F4EE` |
| `color.surface.raised` | `#FCF3EE` | `#FDFBF7` |
| `color.surface.sunken` | `#F6E7DE` | `#EFE9DF` |
| `color.line.subtle` | `#E9CDBF` | `#E5E2DD` (`ink.primary` at 8% on the page, as a solid color) |
| Accent, ink and status colors | Current values | No change; accent on the new page is 5.45:1 |
| `type.family.sans` | `space-grotesk` | `instrument-sans` |

## Decisions

1. **Surfaces:** warm paper, not v9's peach.
2. **Interface font:** Instrument Sans for now. Fonts must stay easy to swap, so each theme chooses its own; see "Fonts" in section 2 of `docs/COMPONENT_PLAN.md`.
3. **The chat runs the app (2026-11-01).** One conversation view is used by a dock that minimizes to a pill, the session page and setup. Agents talk to the person on Today, and to each other in the Agent channel. Anything waiting on the person shows the same count in the sidebar, the pill and Today.
4. **Chat rendering:** the person's messages sit in a tonal bubble with copy, edit and time on hover. Replies are plain text on the page with copy and time. Work folds behind one thinking line, and next steps are rows. Decisions get cards. Their shapes come from Beautiful UI and AICSS's free components, on our tokens.
5. **Motion:** Motion for panels, cards and the sidebar highlight, with the theme's durations and easing, and it honors reduced motion. A loop is allowed only for work really running.

