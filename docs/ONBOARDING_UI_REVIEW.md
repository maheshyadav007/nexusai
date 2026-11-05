# Onboarding and workspace UI review — 4 November 2026

These corrections are developed in `codex/onboarding-sandbox`, a separate worktree. They are not included in the published Beta 0.1.0 until a subsequent release is built.

## Reported issues and corrections

| Feedback | Finding and correction |
|---|---|
| Unnecessary token disclaimer | Removed the deterministic/no-token implementation detail from Posty's welcome copy. The guide still uses fixed text. |
| Landing and setup feel like a form | Rebuilt first-run UI as a Posty-led two-column layout. Posty explains one concise action on the left and the relevant controls sit on the right. The landing keeps one short product example instead of a second block of explanatory text. There is no top rule; a centered 320px divider separates the columns on wide screens. |
| Profile step too tall | First run now asks only for name, role, writing tone and signature in a responsive two-column grid. Appearance, important people and About me remain available in Settings. Controls use quiet labels and bottom-rule fields; smaller viewports stack and scroll within the setup content. |
| Posty blends into cards | Removed the guide's card background/border, enlarged its layout slot to 72px, and increased the name/message hierarchy. Its icon and name use the current accent. Reduced motion and screen-reader text remain supported. Posty appears only during landing and setup, then leaves the application shell. |
| Setup spacing and actions drift between pages | Every desktop step now uses the same centered 520px content frame. The right heading, explanatory note, controls and footer follow one vertical rhythm; Back and the primary action use fixed anchors across all five pages. Narrow layouts reset their contained scroll to the top when the step changes. |
| Setup has too many pages and too much copy | The active path is Home, profile, mail, local search and permissions. Pages move vertically with reduced-motion support. Recovery-key presentation, appearance selection, PST import and search diagnostics no longer interrupt first run. |
| Shared mail configuration appears user-specific | Onboarding asks only for the user's mail login. The server comes from deployment configuration; PST/archive import remains in Connectors. If a deployment has no managed mail server, setup says so rather than asking the user to invent one. |
| Recovery key slows first run | New Beta Homes use the documented default `admin` and do not show a recovery-key page. Settings can replace it with a unique key. Existing moved, locked or damaged Homes retain the recovery flow. This convenience tradeoff is recorded in Known problems. |
| Whole app moves; chat button bottom-left | Tailwind expanded `@apply fixed` in the desktop caption into an additional `.ai-glow:not(.desktop-caption)` rule, overriding the fixed chat launcher. Removed positioning from the glow decorator; each component now owns its position. The app uses dynamic viewport height, disables document overscroll, and contains content-pane scrolling. |
| New folder seems replaced | Empty non-proposed categories were filtered out unless open. They now remain in navigation after another category is created, navigation changes, and reload. Creation is outside the scrolling category list. |
| Sidebar spacing | Removed the mail section's forced growth/blank gap, added horizontal section dividers and bounded category scrolling; short viewports retain a navigation-scroll fallback with Settings fixed below. |
| Web mode lacks app controls | Following the operator's clarification, the web Settings menu offers Reload tab and Close tab. Closing is best effort: browsers may block closing a manually opened tab, so a toast explains how to close it. These actions do not stop backend/frontend servers. Electron retains its graceful Restart/Quit actions. |
| Related Windows chat overlap | The attached chat panel now measures and clears the desktop caption rather than placing its header underneath it. |

## Evidence

- `npm run check`: type checks, design-token/hardcoded-value checks, module boundaries and all 19 frontend tests passed.
- The redesigned first-run journey passed end to end on disposable services at 1280×800, including Home creation, resume/back, mail skip, local-search download failure, permissions and entry to Today. Its accessibility scan passed at every stage.
- Desktop screenshots were reviewed for landing, all five setup stages and Today. A separate 390×844 run passed the entire stacked flow without horizontal overflow. The Today capture and browser assertion confirm that no Posty guide remains after setup.
- Isolated browser acceptance: all 11 first-run/recovery/accessibility and Beta UI checks passed. After the caption correction, all five Beta checks passed again, including the desktop bridge mock and panel/header geometry.
- Final production build passed separately from the running onboarding instance.
- Regression checks cover an empty category surviving another creation and reload; a fixed bottom-right chat launcher at 1080×720; zero document scrolling; viewport reachability of Agent/Planner with 25 categories; compact profile controls; web menu actions; and desktop update controls.
- The live sandbox was reviewed with screenshots. An upward scroll at Today left `window.scrollY = 0`, `main.scrollTop = 0`, navigation top at zero, and document height equal to the 799px viewport. The launcher computed position is `fixed` with a 16px bottom/right inset.
- QA output is local and ignored: `.release/ui-review/review-final.log`, `caption-review.log`, `production-build-final.log`, and preserved `screenshots/` artifacts.
- Native Windows interaction still requires target-device acceptance; the caption test uses a browser desktop-bridge mock. Mac scroll containment was inspected, but every browser/trackpad combination is not certified.

The test environment uses disposable fake mail/model services and separate app data. The operator's active sandbox Home and original running application are preserved.

- Web Close tab was clicked in the live browser. The browser blocked automatic closure and the explanatory toast appeared, as intended. Reload behavior is covered by browser acceptance.
