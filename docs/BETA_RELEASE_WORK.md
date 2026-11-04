# Beta release work

App name: **NexusAI**. **Posty** is a deterministic setup guide, not a model-driven onboarding agent. Preserve the existing Chief of Staff runtime identity and history. Mascot artwork is the final, low-priority task. Use an outline robot for now; a later Python pass may create the requested monochrome, dark-accent Posty with larger eyes and no eye sockets.

## Scope and acceptance

- Offer launch after installation; provide app/shortcut icons and a searchable NexusAI Beta name.
- One integrated Windows header with native window controls. Move app actions into the sidebar Settings drop-up: Settings, About & Updates, Restart and Quit. Graceful shutdown remains mandatory.
- Instrument startup stages, start local services concurrently, and explain progress rather than showing an indefinite spinner.
- Posty provides deterministic, progressively revealed, reduced-motion-aware guidance on landing/setup and unfinished setup across app pages. Explain email download and safe background continuation. Improve the first Today experience.
- Remove the separate chat-model onboarding page; use the first available model by default while retaining model settings. Investigate discovery/download paths without embedding internal credentials.
- Password visibility controls; bounded category/folder navigation with a subtle scrollbar; Windows reminder notifications/sound and a test action.
- Chat only: Preparing with spinner until actual content; then retain the existing Thinking/tool presentation. Remove chat response generation glow. Preserve AI glow in other features.
- Agent thread reads list attachment document keys, extraction status and clear access instructions. Regression-test attachment reads.
- Defer custom Posty artwork/eye tracking until last. Use an outline robot placeholder now; deterministic text respects reduced motion. Do not ingest old pet generation runs into the repository.
- Investigate the two Windows reliability failures rather than skip them. Verify source fencing and digest completion against deterministic tests.
- Test frontend checks/build, targeted backend correctness, isolated onboarding/browser UI, desktop startup/shutdown and Windows install/update. Publish a Beta test release with accurate update-feed limits; internal update hosting remains separate.

## Evidence

Implementation and validation results will be recorded here. A successful installation test from the operator is acknowledged; it does not substitute for the remaining regression and update checks.


## Local validation and remaining gates

- 19 frontend tests, type checks, hardcoded-value checks and module boundaries passed.
- Six first-run browser/accessibility checks passed on isolated services, covering landing, setup/resume, removed chat-model page and recovery flows.
- 121 desktop/scheduler/mail regression and native-TLS checks passed locally; an additional models/search selection (122 checks) passed before the native trust-context switch. Final full backend and Windows validation remain in progress.
- Native TLS verification was tested with a temporary CA/server: trusted additional root accepted; unknown issuer and wrong hostname rejected. This does not prove trust of any particular internal CA or download host.
- The stale-judgment test now waits for listener enqueue as well as persisted mail, preserving its one-final-judgment assertion. The digest test waits for terminal completion after the cursor, preserving empty-output and retry assertions. The fake provider now distinguishes an empty response from its default reply and fails an unreleased gate explicitly. Windows rerun remains required.
- Custom monochrome Posty artwork and eye animation are explicitly deferred by the operator. Icon is a temporary Lucide outline robot; app name stays NexusAI.
- Target-device mail, corporate model/download connectivity, sound policy, first-launch timing and internal update-feed acceptance remain operator tests.

- Additional UI acceptance checks now cover password visibility, a populated/scrolling category list with Agent and Planner remaining visible, integrated desktop-header actions, Settings drop-up and staged update controls. Screenshots are retained in the isolated QA output. Native Windows buttons are verified separately by packaged Windows evidence.
- The full local backend run exposed an additional setup race in the digest test: initial mail queue settlement must precede asking Run now for a digest. The superseded Beta run was cancelled before publication; the setup wait was corrected without changing product behavior.


## Final local acceptance

- Full backend: **816 passed, 1 skipped, 12 speed checks deselected**. Two existing LangGraph beta-protocol warnings; no test failures.
- Frontend: **19 tests**, type checks, hardcoded-value checks and layer boundaries passed. Standalone production build passed.
- Browser: **8 checks passed**, including six first-run/recovery/accessibility checks and two Beta desktop-control/password checks. A 25-category fixture verifies that Agent and Planner remain in the viewport. The Windows bridge is mocked only for these browser layout/control tests.
- Actual Electron 45.2.2 with Node 22.23.4 server: startup/render/shutdown smoke passed with no renderer errors; a separate real sandboxed preload/IPC status request passed. The local Mac startup log measured 1.739 seconds to page load; this is not a Windows performance claim.
- The superseded release run was cancelled before publication. The replacement [Windows Beta validation](https://github.com/maheshyadav007/nexusai/actions/runs/41850625879) uses source commit `c762d16`; publication remains gated on its result.
