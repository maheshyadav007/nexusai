# Desktop build and release manual

NexusAI separates generic source development, deployment customization, and distribution. This manual describes the checked-in automation and its acceptance gates. It contains no deployment-specific hostnames, accounts or credentials.

Status: generic Windows CI passed on 4 November 2026 at commit `3e459f3`: installer build, installation, A-to-B auto-update and data-preservation checks. See the [Windows validation run](https://github.com/maheshyadav007/nexusai/actions/runs/41814312165). The backend bundles `tzdata` and tests named zones without system timezone data. A normal organization-device test, private configuration, internal feed and signed distribution remain unverified; the CI installer uses a temporary loopback feed and must not be distributed.

Node is pinned to **22.23.4** in `desktop/toolchain.json` and `.nvmrc`. Frontend and release-tool package engines require `>=22.23.4 <23`. This is the [21 October 2026 Node 22 security release](https://nodejs.org/en/blog/release/v22.23.4), replacing 22.22.3. The wrappers select/download the pinned runtime and Windows packages bundle it for the Next.js server. Electron carries its own embedded Node runtime; changing this pin does not replace Electron’s runtime. Existing installers must be rebuilt to receive the new bundled server runtime. Node 22.23.4 passed frontend checks (19 tests), release-tool tests (8), an isolated standalone production build, a desktop startup/render/shutdown smoke check, and [Windows installer/update validation](https://github.com/maheshyadav007/nexusai/actions/runs/41827023484). That hosted run used the runner’s default timezone and did not establish non-UTC scheduling correctness.

Scheduling uses `tzlocal` to discover the OS IANA timezone, including Windows registry mappings, while `tzdata` supplies the named-zone database. An explicit `TZ` takes precedence. The Electron launcher also passes its detected IANA zone to child services when `TZ` is unset, and the scheduler preserves the OS clock offset. Hosted CI now sets the disposable runner to India Standard Time, tests backend detection without `TZ`, and runs scheduler/mail reliability checks before packaging. Previously saved schedules may already contain an incorrect explicit `UTC` zone; inspect and re-save those schedules with the intended timezone. The app does not silently rewrite saved UTC schedules, since UTC may have been chosen intentionally.

Latest validation: the [expanded non-UTC Windows run](https://github.com/maheshyadav007/nexusai/actions/runs/41831647703) passed timezone detection and scheduler regressions, but stopped at backend tests with 117 passed and two email-reliability failures. It did not create an installer or exercise updates for the timezone-fixed source. Investigate stale-judgment counting and digest cursor/completion synchronization as recorded in [Known Problems](KNOWN_PROBLEMS.md#windows-email-reliability-validation). Source fixes may be merged while this investigation remains open; distribution acceptance still requires a green full run and target-device checks.

## 1. Validate the generic Windows app first

Commit the source, desktop tools and workflow. From a development checkout on macOS or Linux:

```sh
./desktop.sh ci-trigger
```

This pushes a unique `desktop-ci/...` tag to `origin`, which starts `.github/workflows/windows-desktop.yml` on a standard GitHub-hosted Windows x64 runner. Git authentication uses the existing Git setup. No GitHub CLI, internal server, deployment profile, model credential or mail account is needed. Review progress in the repository's Actions tab.

The workflow can also be started with **Run workflow** after its definition exists on the default branch. It runs on explicit CI tags or manual dispatch; ordinary development pushes do not automatically launch the relatively expensive two-build job.

The job is designed to:

1. Bootstrap pinned Node, uv and Python, using committed dependency lockfiles.
2. Build generic unsigned version A, install its actual NSIS installer, render the app and verify clean shutdown.
3. Build version B and smoke-test its packaged executable without replacing the installed A.
4. Start a loopback-only update feed, launch A, write synthetic database/browser/app-data fixtures, download B through `electron-updater`, install it and relaunch.
5. Confirm B's version and preserved database settings, browser storage, app-data marker and open Home, then exit cleanly.
6. Upload the generic B installer, screenshots, logs and JSON results as short-lived Actions artifacts.

The CI app is named **NexusAI CI** with a distinct application ID and test data. Its installer embeds an ephemeral loopback update URL and is a validation artifact, not a distribution release. It never uses a deployment profile or contacts an internal mail/model server. This update probe exercises a full installer download; it does not certify differential downloads, code signing, real-mail behavior or an internal HTTPS feed. Hosted Windows images already contain development tools and system libraries, so this is not a substitute for a normal target-device test.

Standard GitHub-hosted runners are free for public repositories. Private repositories consume the account's included Actions usage and may incur charges after it is exhausted; artifact storage has its own limits. The workflow has a 60-minute timeout and retains artifacts for three days. Check the repository's Actions/billing settings before repeated runs. GitHub Enterprise Server requires self-hosted runners rather than GitHub-hosted Windows VMs. See [GitHub's runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

Iterate on the generic build until this job is green. Do not add internal credentials to the workflow to make it pass. Local Windows execution of the same generic check is `desktop.cmd ci`, intended for a fresh disposable runner/VM.

## 2. Prepare a private deployment profile

After pulling the intended source revision on the deployment operator's Linux machine:

```sh
./desktop.sh profile-init
```

Edit the two generated files:

| Local file | Purpose |
|---|---|
| `.release/profile/release.json` | Version, update URL, SSH upload host/account, server paths/port, optional signing configuration |
| `.release/profile/company.env` | Internal mail/SMTP defaults, model endpoint/names, optional shared model credential |

These files are ignored by Git. `deployment/company.example.env` and `desktop/release.example.json` are the neutral tracked templates. An operator does not need to edit application source to configure internal services.

Example release configuration:

```json
{
  "schemaVersion": 1,
  "version": "0.1.0",
  "companyEnvFile": "company.env",
  "embedCredentials": false,
  "updateBaseUrl": "http://UPDATE-HOST:8088/windows/x64/",
  "signing": { "enabled": false, "publisherName": "", "certificateFile": "" },
  "ssh": { "host": "SSH-HOST", "port": 22, "username": "UPLOAD-USER", "privateKeyFile": "" },
  "server": {
    "root": "/srv/nexusai-updates", "port": 8088,
    "tlsCertificate": "", "tlsKey": ""
  }
}
```

The public update URL and SSH upload host may differ. The supplied Nginx setup serves `/windows/x64/` beneath `server.root`; include that path and a trailing slash. Set the intended feed URL before building an installer that should update itself. An installer built with an empty URL is local-only.

The environment template supports `NEXUSAI_MAIL_HOST`, mail protocol/port/TLS/label/domain, SMTP settings, `NEXUSAI_MODEL_URL`, model names and tool support. Individual account sign-ins normally happen inside the app. Unknown credentials are not inferred or generated by these tools.

By default, only an allowlist of service defaults is embedded in the installer; credential fields such as `NEXUSAI_MODEL_API_KEY` remain in the private profile. For a deliberately internal deployment that needs a shared key embedded, set `embedCredentials` to `true`: the entire company.env then ships in the installer and can be extracted from it. Keep that installer and profile out of public releases and generic CI. This setting does not embed SSH passwords or signing-key passwords.

Package the profile:

```sh
./desktop.sh prepare-profile
```

This creates `.release/deployment.zip` and applies the profile locally for optional host administration. The portable ZIP includes the configuration, company.env and any explicitly configured local PFX/SSH key files. Passwords are never saved. Treat the archive as deployment material and transfer it through an internal channel to the Windows build machine/VM. Do not commit it or upload it as a public CI artifact.

## 3. Build the customized app on Windows

Pull the corresponding committed source, transfer the deployment ZIP, then run:

```powershell
.\desktop.cmd apply-profile -Profile C:\Deploy\deployment.zip
.\desktop.cmd build-test
```

`apply-profile` relocates paths and writes ignored `desktop/release.local.json`. Relative paths inside a profile are resolved relative to its profile folder; command-line `-Profile` paths are relative to the repository root. Windows JSON paths use doubled backslashes or forward slashes.

`build-test` checks source cleanliness, copies tracked application source to `.release/build`, installs locked dependencies, checks Windows native imports, runs focused backend and frontend checks, builds the standalone Next.js server, bundles Python and Node, builds the installer, installs it in a pipeline test directory and launches an isolated smoke test. It then opens the installed app for hands-on checks. Existing web build output and Python environments are not replaced.

The first build downloads tools and dependencies and may take several minutes. Later complete builds automatically increment the patch version. To select an explicit version:

```powershell
.\desktop.cmd build-test -Version 0.1.1
```

Unsigned customized builds use **NexusAI Pilot**, a separate app ID/data directory and an `unsigned/` feed. Signed builds use **NexusAI**. CI uses a third identity. Do not simultaneously open the same Home from different installations.

A customization has this precedence: bundled deployment defaults, then the user's app-data `company.env`, then explicit process environment. `open` and `build-test` copy the profile's complete company.env to the build operator's app-data directory for testing; it is not automatically copied to every employee unless embedding was enabled. Other users can configure sign-ins through the app or receive a local company.env through the deployment's chosen onboarding process.

## 4. Test before distributing

The automated smoke test verifies startup readiness, the authenticated frontend proxy, a nonempty page, renderer/HTTP asset errors, screenshots and clean service exit. Reports live under `.release/smoke/`, with `smoke.json` beside the installer. Review the screenshot.

- `build-test` and `install-test` install the actual NSIS output in `%LOCALAPPDATA%/NexusAI-Pipeline-Pilot` or `NexusAI-Pipeline-Signed`.
- `test` and `release` smoke-test `win-unpacked` without replacing the older installed version, preserving it for an A-to-B update check.
- Installer tests update Windows app registration even with a custom install path. Signed installer tests belong in a disposable account/VM; the command refuses a signed install test if the normal app-data directory already points to a Home.

After generic CI passes, test on a normal target Windows device: internal certificates/proxy access, real test-mail sync and a controlled send, model access, PST import, sleep/wake, settings/history preservation, update postponement during active work, and the customized A-to-B-to-C update chain. GitHub CI cannot establish these organization-specific conditions.

## 5. Set up internal distribution after validation

The internal host needs SSH/SFTP, systemd and sudo/root for one-time setup. Automatic package installation supports apt/dnf; Python >=3.8 and Nginx are required. Use a dedicated release directory. With the applied profile, run from Linux or Windows:

```sh
./desktop.sh server-setup
```

```powershell
.\desktop.cmd server-setup
```

The command prompts for SSH authentication and, when necessary, a sudo password. First-use SSH host fingerprints must be verified and accepted; changed keys are rejected. Keys/passphrases and passwords are not put in the repository or installer. Blank `ssh.privateKeyFile` selects password authentication; blank sudo password selects passwordless sudo.

Setup configures one Nginx site without replacing other sites, creates upload/feed directories and validates Nginx configuration before reload. It can open the configured port in active firewalld. UFW, external firewall rules, SELinux restrictions and DNS may need deployment-specific setup; the script does not disable them. Sudo policies requiring a TTY may need the checked-in setup script to be run from the Linux console.

HTTP is supported for the unsigned internal pilot. HTTPS requires a certificate trusted by target devices; provide server-side certificate/key paths or use an existing trusted reverse proxy. HTTPS certificates and Windows code-signing certificates serve different purposes. Certificate issuance, organizational trust and publisher verification remain explicit deployment decisions.

## 6. Release with one command

On the Windows build machine/VM, after the profile is applied:

```powershell
.\desktop.cmd release
```

This builds the next version, smoke-tests its packaged executable, uploads installer/metadata over SSH, verifies server-side hashes, and atomically advances the pilot feed. Files are versioned and immutable; the channel manifest changes last. A failed upload leaves the previous complete release available. Final checks fetch the public manifest and installer size from the build machine.

If the final HTTP check fails after promotion, files are already published on disk: repair hosting and retry `publish`, without rebuilding. Replacing an existing version with different files or moving a channel backwards is refused. Identical retries are supported.

To reuse an already tested artifact:

```powershell
.\desktop.cmd publish
```

The output prints the installer URL. Users install once; subsequent updates use the embedded feed without source-repository access. Update checks/downloads happen in the background. The native NexusAI menu shows progress, offers **Restart to update**, selects pilot updates for signed installations and opens logs. Active requests, agents and imports postpone restart. Services are drained before installation, with no force-kill of Python. Agent completion persists final output, final status and turn closure together.

## Signing and stable promotion

Unsigned generic CI and unsigned pilot tests do not require signing procurement. For signed distribution, the supplied implementation supports a local PFX plus publisher name; enter its password at the build prompt or use process-local `CSC_KEY_PASSWORD`. Hardware/cloud signing services require their own integration. A self-signed certificate does not automatically become trusted and signing does not guarantee device-policy/SmartScreen acceptance.

Signed apps default to the stable channel. Enable **Receive pilot updates** to validate a signed pilot, then promote exactly the same tested artifacts:

```powershell
.\desktop.cmd publish -Channel stable
```

Stable promotion requires signed artifacts, HTTPS, matching smoke evidence and confirmation that real update/mail acceptance passed. It does not rebuild. For a bad release, publish a higher-version fix; an older manifest cannot downgrade already updated clients. Preserve Home backups/recovery material and verify database compatibility before restoring an older binary.

## Command reference

| Command | Purpose |
|---|---|
| `desktop.sh ci-trigger` | Push a CI tag and start generic GitHub Windows validation |
| `desktop.cmd ci` | Execute the generic Windows A-to-B check on a fresh runner/VM |
| `desktop.sh profile-init` | Create local deployment templates |
| `desktop.sh prepare-profile` | Export/apply a portable private deployment profile |
| `desktop.cmd apply-profile -Profile <ZIP>` | Import that profile on the Windows builder |
| `desktop.cmd init` | Alternative interactive local configuration without a profile |
| `desktop.cmd doctor` | Diagnose tools/configuration |
| `desktop.cmd build` | Build only |
| `desktop.cmd test` | Smoke-test packaged output without reinstalling |
| `desktop.cmd install-test` | Install and smoke-test the actual installer |
| `desktop.cmd build-test` | Build, install, smoke-test and open the app |
| `desktop.cmd open` | Open the existing pipeline test installation |
| `desktop.cmd server-setup` | Provision the internal Nginx host |
| `desktop.cmd release` | Build, test and publish to pilot |
| `desktop.cmd publish` | Publish existing tested files |

Unix profile/hosting/publication commands use `desktop.sh`; the actual Windows application build requires Windows x64. Development and profile creation can run elsewhere. No dedicated self-hosted runner is needed for generic GitHub.com validation.

## Troubleshooting and limits

- Build source changes must be committed. Build commands never pull, switch branches, stash, commit or push source. Only `ci-trigger` deliberately creates/pushes a CI tag.
- All generated tools, artifacts, profiles and evidence are under ignored `.release/`; machine configuration is also ignored. Linux scripts retain LF in Windows checkouts through the repository attributes.
- Download access is needed for pinned Node/uv/Python, npm/PyPI, Electron assets and build-time fonts. Scripts inherit proxy/index settings. Windows uv uses system certificates; Node can use `NODE_EXTRA_CA_CERTS`. Different downloaders may need separate proxy configuration. Keep certificate verification enabled; approved mirrors/pre-seeded caches may be needed on restricted networks.
- The Windows wrapper changes PATH/execution policy only for its own process. Enforced device policy still applies. A package/native DLL failure stops the build rather than installing dependencies on employee startup. Third-party MCP commands may still need separately managed external prerequisites.
- SSH success does not prove HTTP download access. Check URL/path, certificate trust, directory permissions, Nginx logs, DNS and firewall/proxy access from a target device.
- Application logs are under the app-data directory for NexusAI, NexusAI Pilot or NexusAI CI; smoke logs are in the test directory. Review application context before sharing logs.
- The frontend chooses a free local port once and saves it in app-data `frontend-port`, preserving its browser origin/storage across restarts and updates. A later collision produces an actionable startup error rather than silently changing the origin. Close the conflicting process or restart the device. Backend ports remain dynamically selected.
- CI checks full NSIS updates with synthetic data. Live mail, model quality, custom HTTPS/authentication, differential updates, signing and organizational device controls require their own acceptance evidence. No error-free deployment is claimed before those gates pass.

See [release architecture](WINDOWS_RELEASE_PLAN.md), [technology choices](TECH_STACK.md), [Electron Builder platform limits](https://www.electron.build/v26/docs/features/multi-platform-build/) and [updater documentation](https://www.electron.build/v26/docs/features/auto-update/).
