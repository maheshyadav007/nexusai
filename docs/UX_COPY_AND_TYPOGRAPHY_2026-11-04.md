# UI follow-up: copy, typography and AI-result presentation

## Recovered wording

From the existing draft `docs/IDENTITY_PLAN.md` (left unchanged):

| Current | Previously recorded replacement |
|---|---|
| Needs you | For your decision |
| Allow | Approve |
| Morning brief | Your brief |
| Know you better | First meeting |

There is no recorded agreed replacement for Today. **Your day** is a new recommendation, not a recovered decision. Keep the navigation label stable until choosing the full copy set; applying only some labels can create inconsistencies between Today, Settings, Agents and schedule names. The app name and pet names remain separate identity decisions.

## Font recommendation

Current UI body: Instrument Sans. Instrument Serif, JetBrains Mono and Space Grotesk are already bundled through `frontend/ui/theme/fonts.ts`; Space Grotesk is available but not the current default. No font change was made in this patch: the request was to suggest alternatives.

My preferred pairing: **Space Grotesk for headings, navigation and short controls; Inter for email bodies, briefs and long chat replies.** It keeps the character the user likes while giving long reading a quieter texture. This is a design judgement to compare in the actual app, not a claim that one typeface is universally more readable.

| Option | Suggested use / visual character | Primary source |
|---|---|---|
| Space Grotesk | Distinctive, technical, friendly; first choice for interface identity. Also worth comparing as a single-family app | [Designer repository](https://github.com/floriankarsten/space-grotesk): proportional Space Mono derivative, adjusted for non-display sizes |
| Inter | Neutral long-form reading and dense interface labels; preferred reading companion | [Official Inter site](https://rsms.me/inter/): text/display optical sizes and a tall x-height for small-text legibility |
| Source Sans 3 | Softer, restrained alternative for an email-heavy product | [Adobe's repository](https://github.com/adobe-fonts/source-sans): designed for UI environments |
| IBM Plex Sans | More editorial/technical character; useful alternative if Inter feels too neutral | [IBM Plex](https://www.ibm.com/plex/): official family and specimens |

Trial settings: 400 weight for reading, 500 for controls, 600 sparingly; 16–17px email text, approximately 14px compact labels, 1.5–1.6 line height for prose. Avoid very light body weights and excessive letter spacing. Compare actual long emails, names, numbers, unread rows, drafts and both themes; retain user zoom and accessibility. If multilingual content is important, validate glyph coverage and fallback for the user's languages before choosing.

## Presentation changes implemented

- Managed-chat warning and Still proceed / Lock input now sit inside the composer border. Only the disabled text field is faded, so the warning and override remain legible.
- A new morning brief uses the existing AI surface glow until interaction with that exact brief. Clicks, copied text, editing and keyboard focus acknowledge it. After interaction it retains the stronger AI-result border and soft shadow. This is visual acknowledgement, not a positive feedback/reward event.
- Acknowledgement persists locally per session + brief timestamp, capped at 50 entries. A newly generated version glows again. Another browser/device will maintain its own acknowledgement. If local storage is unavailable, it lasts only in memory.
- Summary and acknowledged brief share a stronger 1.5px multicolor border, subtle outline and soft shadow. The result border is static; only actual AI generation uses the generating animation. The brief attention glow is the prior AI surface treatment.
- AI generation and ordinary system loading remain separate states.

The earlier settings request means **horizontal dividers between sections**, not an added vertical divider. This patch does not change that interpretation.

## Verification

Frontend typecheck, hardcoded-value check, import-boundary check and 19 tests passed; production build passed. Backend chat/trigger/history regression suite: 83 passed (two existing LangGraph experimental-stream warnings). Browser checks on a separate synthetic Home verified warning nesting, disabled → override → locked input, glow → border on interaction, persistence after refresh and a fresh glow for a regenerated brief. The production frontend was restarted and its API reported Home ready. No live-model email-quality evaluation was run.
