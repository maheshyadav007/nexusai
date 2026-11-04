# Windows installation and reliable updates

Status: implementation and scripts added, 2026-11-04. Follow the [Windows release guide](WINDOWS_RELEASE_GUIDE.md) for commands and local configuration. No packaged Windows build or Windows update cycle has been verified yet; the acceptance gates below remain required.

## Goal and constraints

Ship a stable Windows desktop app with a complete installer and repeatable updates. Keep the repository deployment-neutral, with generic GitHub.com Windows CI, a separate local customization profile, and an optional internal distribution host. Installed users need no source-repository account or shared GitHub token. Existing organizational installation and network restrictions still apply.

The first supported target is Windows 11 x64. Keep the current React/Next.js and Python application. Do not combine this release with a frontend rewrite, agent redesign, new database format, or a packaging-tool upgrade.

## Smallest operational design

1. Develop the generic application and scripts on any supported development system. Trigger the GitHub.com Windows validation workflow using `desktop.sh ci-trigger`; it builds generic A/B versions, installs A, and tests its update to B against a loopback feed. After that gate passes, an operator prepares a private deployment profile on Linux, transfers it to a Windows x64 machine/VM, and uses the same build tools for customized artifacts. Internal distribution is a later gate.
2. Electron supervises the packaged Next.js standalone server and bundled Python backend. Bundle all runtime dependencies; users do not install Node, Python, uv, or development tools. Verify the Node execution mechanism and Next.js standalone compatibility in the packaging spike before standardizing it.
3. Build a full per-user NSIS installer with electron-builder. Use electron-updater's generic HTTPS provider. Pin compatible stable versions; do not adopt unreleased builder/updater behavior from the documentation's default branch.
4. Serve release files from a small internal HTTPS host, such as Nginx with persistent storage. The release script copies artifacts to this host. Employee clients never fetch private GitHub assets directly. No custom update API or on-demand GitHub proxy is needed initially.
5. Maintain separate pilot and stable feed directories, with versioned immutable installers and generated metadata. Validate uploads and atomically replace the channel manifest last. Keep old artifacts for recovery and clients with pending downloads. Disable caching of channel manifests; allow caching of immutable versioned files. Test byte-range responses if differential downloads are enabled.

Example paths, not provisioned addresses:

```text
https://<internal-host>/nexusai/windows/x64/pilot/
https://<internal-host>/nexusai/windows/x64/stable/
```

The host must be directly reachable by intended users, including users without GitHub access. If network restrictions permit, intranet/VPN-only read access avoids another login flow. Protect publishing access separately. Browser SSO redirects are not a background-download authentication solution. Use an HTTPS certificate already trusted by target Windows machines; do not disable certificate checks to make the feed work.

## Signing: prove feasibility before choosing procurement

HTTPS certificates identify the download server. Windows code-signing certificates identify the software publisher. These are separate requirements and neither replaces the other.

First run a disposable, unsigned packaging/update experiment on a representative company laptop, only if its policy permits it. Keep it separate from the eventual employee installation identity and data. Any unsigned update experiment must explicitly configure the pinned toolchain for that purpose and document the reduced verification; do not silently weaken production verification. An unsigned success is not evidence that a signed production update works.

For the employee release, prefer an existing company signing identity or an appropriate trusted signing service/certificate. Verify actual signing access from the build machine, trust on target machines, and the publisher identity accepted by the updater. A self-signed certificate does not automatically become trusted, and a purchased certificate does not guarantee SmartScreen or company-policy acceptance. Do not require users to disable Windows protection. Choose the signing approach before the persistent pilot rollout and verify the full signed install/update chain there.

## Implementation gates

| Gate | Work | Evidence required before proceeding |
|---|---|---|
| 1: packaging feasibility | Package the current app on Windows; exercise SQLCipher, PST worker imports, optional native libraries, Next.js routes and SSE | A clean Windows machine with no developer runtimes starts the installed app, opens a test Home, reads mail fixtures, streams an agent response and closes all child processes |
| 2: distribution feasibility | Start the internal file host; test the chosen signing approach and a minimal two-version update | A standard company account without GitHub access downloads, installs and updates through the real network/certificate path |
| 3: complete app lifecycle | Startup readiness, single instance, dynamic loopback ports, actionable startup failures, safe shutdown and update coordination | No orphan services, duplicate schedulers, port conflicts, lost drafts or interrupted sends during the test scenarios below |
| 4: pilot release | Package the real app as A, then update A to B and B to C using representative copied data | Two consecutive installed-app update cycles pass on a clean VM and a normal company laptop; versions, settings, history and credentials remain correct |
| 5: repeatable publication | Automate the proven release script, archive to GitHub, publish pilot, then promote the exact tested artifacts to stable | A tagged release produces traceable artifacts and checks; stable promotion does not rebuild the installer |

Packaging and update feasibility are the first deliverables. Defer visual native effects, automatic startup, advanced rollout controls, custom updater infrastructure and macOS distribution until the Windows path passes these gates. Packaging tests on Mac do not establish Windows compatibility.

## Runtime and update behavior

- Keep a permanent app ID, installation identity, Home location and app-data location. Store neither the Home nor credentials in installation/version directories. An update replaces the frontend and backend together as one compatible app version. Preserve data on ordinary uninstall by default.
- Bind local services to loopback. Retain existing access checks, Electron isolation and a narrow preload bridge. Internal distribution does not require exposing the local mail API to the network.
- Supervise child services with readiness checks, bounded recovery and logs. Do not display the main UI as ready before required services and migrations are ready. Distinguish connectivity failures from startup failures.
- Check for updates after startup and periodically with backoff; provide Settings > Check for updates. A failed check or download must leave the current version usable. Show progress and a clear failure reason with retry.
- Download in the background. Apply on an explicit restart or a coordinated normal exit after work is safely stopped. Do not force restart an active email send, import or agent run. Offer postponement. Disable uncontrolled automatic installation paths until shutdown coordination is verified.
- Before installation, stop scheduling new work, persist drafts/checkpoints, settle or explicitly pause current work, close databases and stop child processes. If safe shutdown fails, postpone installation rather than killing an email send. On restart, reconcile unfinished work before retrying; never blindly resend an email whose delivery outcome is uncertain.
- Database backups and migrations must use consistent SQLite/SQLCipher-aware procedures after writers stop. Include both application and checkpoint state where needed, and preserve key/recovery material. Verify restore using copied data. Never delete the existing Home after an upgrade error.
- Do not promise automatic binary rollback across incompatible database changes. Prefer backward-compatible migrations initially. A bad release is stopped for further distribution, then replaced by a higher-version fix. Retain known-good installers, compatible backups and a documented recovery procedure.
- Record app/frontend/backend version, update state, migration result and startup errors in local diagnostics. Support copying diagnostics without including email bodies, credentials or tokens by default.

## Minimum release verification

Test the installed app, not only a development-mode updater:

- First install, launch, normal quit, reopen, Windows restart and single-instance activation.
- A to B to C update; skipping B; a user that remains on an older version; signed publisher validation.
- Preserve test email history, drafts, feedback, schedules, account settings, credentials and selected Home across updates.
- Real API/SSE streaming, mail sync and a controlled mail send; verify updates cannot cause duplicate sends or duplicate scheduled runs.
- PST worker, attachment handling and native database/model dependencies on Windows; connector commands must explain any external prerequisite rather than silently assume npx/uvx exists.
- Offline/VPN disconnected, unavailable host, corporate proxy/certificate chain, partial download, corrupt artifact, disk full, locked files and a cancelled restart. A server certificate accepted by a browser alone does not prove Electron/Python trust works.
- User exits with work active, system sleep/wake, frontend/backend startup failure and migration failure. Verify recoverability with a copied Home.
- Publication interruption: clients see the previous complete release until the new complete release is promoted. Verify stable and pilot feeds stay separate and the installer embeds the intended feed.

Use a clean Windows VM for repeatable checks and a normal company laptop for actual policy, antivirus, certificates and proxy behavior. Maintain a small pilot group before wider distribution. No dates or success claims until the gates produce evidence.

## Inputs to establish early

- A Windows x64 build/test machine and one representative company laptop.
- An internal host with persistent storage, a stable address and an HTTPS certificate trusted by target machines; verify intended employees can reach it.
- Whether company signing credentials/service already exist and are usable for this application.
- Whether GitHub Actions/self-hosted runners are available. This does not block an initially manual, repeatable release script.

## References

- [electron-updater, generic feeds, NSIS, installed-app testing and staged updates](https://www.electron.build/v26/docs/features/auto-update/).
- [Windows build/signing configuration for the stable v26 documentation](https://www.electron.build/v26/docs/win/).
- [Next.js standalone output](https://nextjs.org/docs/app/api-reference/config/next-config-js/output).
- [GitHub Enterprise Server self-hosted runners](https://docs.github.com/en/enterprise-server%403.19/actions/reference/runners/self-hosted-runners).
- [Microsoft Smart App Control and code signing](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview).
