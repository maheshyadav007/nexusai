# Side-by-side Windows updates

## Why

Updates failed with "Could not remove the previous installation (uninstaller exit code 2)", while uninstall followed by a fresh install worked.

Root cause, confirmed on a Beta laptop: electron-builder's NSIS update ran the *previous* version's uninstaller. That uninstaller moves every installed file (14,160 of them) out of the way and gives up after about five seconds if any one is locked. A background scanner held a contiguous alphabetical range of `resources\python` files for minutes. A manual uninstall uses a plain delete that skips locked files, so it never failed.

Squirrel.Windows (used by the Claude desktop app) avoids this but always installs on C: with no folder choice. Velopack allows a folder choice but swaps one folder in place with short retries and force-kills processes. MSIX needs a trusted signing certificate. NexusAI therefore keeps the electron-builder NSIS installer, with its folder choice, and changes what it does.

## Layout

```
<folder chosen at first install>\
  NexusAI Beta.exe            launcher (desktop/installer/launcher.nsi); shortcuts, pins and Apps point here
  Uninstall NexusAI Beta.exe
  nexusai-install.ini         [Install] Current=<version>: the version the launcher starts
  app-0.2.0\                  previous version: left alone, removed once free
  app-0.2.1\                  current version; .nexusai-complete marks it usable
  logs\launcher.log
```

App data, Home, mail, settings and browser storage stay in `%APPDATA%\NexusAI Pilot` (or `NexusAI`) and the user's Home folder. Installs, updates and uninstalls never touch them unless the user asks.

## Install and update

1. **Location:** the first install asks for a folder, defaulting to `%LOCALAPPDATA%\Programs\<Product>`. Later installs and updates always use the registered folder. Choosing another folder while NexusAI is installed explains that the update goes to the existing folder; moving means uninstalling first, and data is kept.
2. **Checks, before anything changes:**
   - The folder is not a drive root or the data folder.
   - The installer is not running from inside it.
   - The version is not older than the installed or active version.
   - The folder is writable.
   - There is enough free space on the install and temporary drives.
3. **Add:** the app is unpacked into a new `app-<version>`. Nothing in use is touched, so NexusAI may keep running. A same-version repair unpacks beside the existing copy and swaps only if that copy is not in use.
4. **Verify:** the program, `app.asar`, launcher and uninstaller must be present. Then `.nexusai-complete` is written.
5. **Root files:** the launcher and uninstaller are replaced atomically (`MoveFileEx`, retried up to 60 s). If the launcher is in use on an already converted installation, the existing launcher stays; it reads the same pointer.
6. **Switch:** `nexusai-install.ini` is written to a temporary file and atomically replaces the old one. Until this step, the launcher keeps starting the previous version.
7. **In the app:** the update downloads with electron-updater, the installer runs silently while you work, and Settings shows "Restart to update". Restart drains local services as before (no force-kill of Python), checks that no bundled service is still running, and starts the launcher with `--wait-pid`. The new version starts only after the old process has exited.
8. **Cleanup:** every 15 minutes the app retires old version folders, abandoned staging folders (older than 6 hours) and leftovers of the single-folder layout. A folder goes only if renaming it succeeds, which proves nothing holds its files; otherwise it waits for the next pass. It never touches the running version, the active version or anything newer.

A `Setup.exe` run by hand while NexusAI is open works the same way. The open app notices the activated newer version and offers a restart.

### Launcher

The launcher reads the pointer, accepts only a dotted version, and checks that `app-<version>` has its program and completion marker. If the pointer is missing, damaged or names an unusable folder, it starts the newest complete version. With `--wait-pid=<pid>` it waits up to 60 s for that process to exit. Failures are logged to `logs\launcher.log` and shown with a code. Taskbar pins relaunch through the launcher (`setAppDetails`), so they survive the removal of old version folders.

### Converting a single-folder installation (one time)

An installation from Beta 0.1.0 or earlier has the app directly in its folder. The update from it:
1. Waits for NexusAI to close, as before.
2. Records the folder's existing entries in `.legacy-files`.
3. Moves the old program aside, retrying up to 120 s. If it can't, nothing has changed yet and the user is asked to retry.
4. Adds the launcher and the new version, and switches.

If the launcher can't be placed, the old program is moved back. The app then deletes exactly the recorded entries, by name and only in that folder, once they are free.

## Uninstall

The first page explains that data is kept and offers **Also delete my NexusAI data from this computer**, unticked. Ticking it asks for confirmation. Silent uninstalls keep data unless `--delete-app-data` is passed.

Deleting data (`desktop/installer/remove-user-data.ps1`) removes:
- the installation's data folder;
- NexusAI's own folders and `home.json` in the Home folder, the same rule as the app's Home reset. Other files in Home stay, and links are removed rather than followed.
- saved sign-ins under the shared `NexusAI` service in Windows Credential Manager.

A Home folder used by another NexusAI installation (signed and Beta) is kept, and so are the shared sign-ins while another installation exists.

Program files are removed with retries for 30 s. Anything a scanner still holds is reported, and the folder can be deleted later. A per-user installer cannot schedule deletion at reboot.

## Error codes

Every failure is logged with its code. Installer logs are in `%TEMP%\nexusai-setup.log`, uninstaller logs in `%TEMP%\nexusai-uninstall.log`, and launcher logs in `<folder>\logs\launcher.log`. Silent installs started by the app return the code, and the app shows the message from `desktop/layout.cjs`.

| Code | Meaning | What the user does |
|---|---|---|
| NX-10 | NexusAI is still running (single-folder conversion, uninstall) | Finish or pause work; retry |
| NX-11 | Safety check could not run (PowerShell or policy) | Send the log; nothing was changed |
| NX-12 | A newer version is installed | Nothing to do |
| NX-13 | The installer is inside the NexusAI folder | Move it elsewhere |
| NX-20 | Unusable folder (drive root or data folder) | Choose a dedicated folder |
| NX-21 | Folder not writable | Choose another folder or ask IT |
| NX-22 | Not enough disk space | Free space, or reinstall on another drive |
| NX-23 | Cancelled: already installed elsewhere | Uninstall first to move |
| NX-31 | Files not unpacked completely | Retry (disk full or a program removed files) |
| NX-32 | Version folder busy | Retry in a few minutes |
| NX-33 | Launcher or uninstaller could not be replaced | Retry in a few minutes |
| NX-34 | Version could not be activated | Retry in a few minutes |
| NX-35 | Old program file locked during conversion | Retry in a few minutes |
| NX-40 | Launcher found no complete version | Run the installer again (repairs) |
| NX-41 | Launcher could not start the app | Run the installer again |
| NX-51 | Uninstall left files that were in use | Delete the folder later |
| NX-52 | Uninstall could not delete some data | The message lists what remains |

Codes 1 and 2 are NSIS's own (cancelled, or another installer already running).

## Code

| File | Role |
|---|---|
| `desktop/installer/installer.nsh` | Location, checks, add/verify/switch, conversion, uninstall page, data removal, file removal, logging, codes |
| `desktop/installer-templates.cjs` | Replaces electron-builder's "run the old uninstaller, unpack over the folder" steps (pinned text; a template change stops the build) |
| `desktop/installer/launcher.nsi` | Launcher |
| `desktop/installer/check-install.ps1` | Process and version safety checks (`version` mode never waits for the app) |
| `desktop/installer/remove-user-data.ps1` | Data removal on request |
| `desktop/layout.cjs` | Pointer, pending version, cleanup, error messages |
| `desktop/main.cjs`, `runtime.cjs` | Silent install beside the running app, restart through the launcher, cleanup schedule |
| `desktop/installer/compile-check.cjs` | `npm run check:installer`: compiles launcher, installer and uninstaller on any OS with warnings as errors |

The bundled Python also drops parts NexusAI never loads: `Lib\test`, IDLE, Tcl/Tk and package `tests` folders. That means fewer files to download and fewer for scanners to hold.

## Tests

- **Unit, any OS** (`npm test`, `npm run check:installer`):
  - pointer parsing and rejecting unsafe values;
  - pending-version rules;
  - cleanup keeping the running, active and newer versions, retrying locked folders, and respecting staging age;
  - removing single-folder leftovers by recorded name only;
  - template patching;
  - the app's install, failure, manual-setup and restart flows;
  - the full installer and uninstaller compiling with `-WX`.
- **Windows CI** (`desktop.cmd ci`):
  1. automatic update while a file of the running version is held open (the update succeeds and the old folder is kept);
  2. downgrade rejected with NX-12;
  3. damaged pointer recovered by the launcher;
  4. orphan Python blocks a restart and unrelated processes are untouched;
  5. a default uninstall keeps data;
  6. manual `Setup.exe` while the old version runs (restart offered, old folder removed);
  7. uninstall with data deletion removes exactly NexusAI's data;
  8. in acceptance, conversion of the published Beta 0.1.0 in its own folder.
- **Manual, on the Beta laptop:** one real update with company security software active, and a fresh install on a second drive.
