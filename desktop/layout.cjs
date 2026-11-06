const fs = require('node:fs');
const fsp = fs.promises;
const path = require('node:path');

// Side-by-side installation, created by installer/installer.nsh:
//   <root>\<Product>.exe            launcher; <root>\nexusai-install.ini names the version it starts
//   <root>\app-<version>\           one complete app per version (.nexusai-complete written last)
//   <root>\.staging-*, .trash-*     interrupted or retired copies, removed here once free
//   <root>\.legacy-files            entries of an old single-folder installation, removed here once free
const POINTER = 'nexusai-install.ini';
const COMPLETE = '.nexusai-complete';
const versionFolder = /^app-((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))$/;
const STALE_STAGING_MS = 6 * 60 * 60 * 1000;

// Installer exit codes (installer/installer.nsh) and what the user can do about them.
const installerErrors = {
  1: 'The update was cancelled.',
  2: 'Another NexusAI installer is already running. Wait for it to finish, then try again.',
  10: 'NexusAI has to close before this update can be installed. Finish or pause your work, then try again.',
  11: 'The installer could not check that it is safe to continue. Nothing was changed.',
  12: 'A newer NexusAI is already installed. Nothing was changed.',
  13: 'The installer is inside the NexusAI folder. Move it elsewhere and try again.',
  20: 'NexusAI is installed in a folder the installer cannot use. Reinstall it into a dedicated folder.',
  21: 'NexusAI cannot write to its installation folder. Ask IT for write access, or reinstall into another folder.',
  22: 'There is not enough free disk space for the update. Free some space and try again.',
  23: 'The update was cancelled.',
  31: 'The update files were not unpacked completely. Try again.',
  32: 'The update folder is in use by another program (often security scanning). Try again in a few minutes.',
  33: 'The NexusAI launcher could not be updated. Try again in a few minutes.',
  34: 'The new version could not be activated. Try again in a few minutes.',
  35: 'An old NexusAI file is in use by another program (often security scanning). Try again in a few minutes.',
};
function installerError(code) {
  const text = installerErrors[code] || 'The update could not be installed.';
  return `${text} (Error NX-${code}. Details: %TEMP%\\nexusai-setup.log)`;
}

function parseVersion(value) {
  const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.exec(value);
  if (!match) throw new Error(`Invalid version: ${value}`);
  return match.slice(1).map(Number);
}

function compareVersions(a, b) {
  const [x, y] = [parseVersion(a), parseVersion(b)];
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] - y[i];
  return 0;
}

// The installation root, or null when this executable is not inside a side-by-side installation.
function installRoot(executable) {
  const folder = path.dirname(executable);
  const root = path.dirname(folder);
  if (!versionFolder.test(path.basename(folder)) || !fs.existsSync(path.join(root, POINTER))) return null;
  return root;
}

function isComplete(root, version, exeName) {
  return fs.existsSync(path.join(root, `app-${version}`, COMPLETE)) && fs.existsSync(path.join(root, `app-${version}`, exeName));
}

// The version the launcher will start next time, or null if the pointer is missing or unusable.
function activeVersion(root) {
  let text;
  try { text = fs.readFileSync(path.join(root, POINTER), 'utf8'); } catch { return null; }
  const match = /^\s*Current\s*=\s*(\S+)\s*$/mi.exec(text.replace(/^﻿/, ''));
  if (!match) return null;
  try { parseVersion(match[1]); } catch { return null; }
  return match[1];
}

// A newer version that is installed, complete and active: it starts on the next restart.
function pendingVersion(root, running, exeName) {
  const active = activeVersion(root);
  if (!active || compareVersions(active, running) <= 0 || !isComplete(root, active, exeName)) return null;
  return active;
}

// Renaming fails while any file inside is open, so a successful rename proves nothing uses the folder.
// A locked folder is left for the next pass; nothing waits for it.
async function retire(target, root, log) {
  const trash = path.join(root, `.trash-${path.basename(target)}-${Date.now().toString(36)}`);
  try { await fsp.rename(target, trash); }
  catch (error) {
    if (error.code === 'ENOENT') return 'gone';
    log(`Cleanup: kept ${target} for now (${error.code || error.message}).`);
    return 'kept';
  }
  return removeTrash(trash, log);
}

async function removeTrash(trash, log) {
  try { await fsp.rm(trash, { recursive: true, force: true }); return 'removed'; }
  catch (error) { log(`Cleanup: ${trash} is partly removed; retrying later (${error.code || error.message}).`); return 'kept'; }
}

// Removes what is no longer needed. Never touches the running version, the active version or anything
// newer than the running version (it may be an update that is being installed right now).
async function cleanup(root, running, log, now = Date.now()) {
  const results = {};
  const active = activeVersion(root);
  let entries = [];
  try { entries = await fsp.readdir(root, { withFileTypes: true }); } catch { return results; }
  for (const entry of entries) {
    const full = path.join(root, entry.name);
    if (entry.isDirectory() && entry.name.startsWith('.trash-')) {
      results[entry.name] = await removeTrash(full, log);
    } else if (entry.isDirectory() && entry.name.startsWith('.staging-')) {
      // An installer may be writing into it right now; only clearly abandoned copies go.
      const age = now - (await fsp.stat(full).catch(() => ({ mtimeMs: now }))).mtimeMs;
      if (age > STALE_STAGING_MS) results[entry.name] = await retire(full, root, log);
    } else if (entry.isDirectory() && versionFolder.test(entry.name)) {
      const version = versionFolder.exec(entry.name)[1];
      if (version === running || version === active || compareVersions(version, running) > 0) continue;
      results[entry.name] = await retire(full, root, log);
    }
  }
  const legacy = await cleanupLegacy(root, log);
  if (legacy) results['.legacy-files'] = legacy;
  return results;
}

// Entries of the old single-folder installation, recorded by the installer when it converted the folder.
const protectedNames = new Set([POINTER.toLowerCase(), 'logs', '.legacy-files']);
async function cleanupLegacy(root, log) {
  const list = path.join(root, '.legacy-files');
  let names;
  try { names = (await fsp.readFile(list, 'utf8')).split(/\r?\n/).map(name => name.trim()).filter(Boolean); }
  catch { return null; }
  let kept = 0;
  for (const name of names) {
    // A recorded name is a single entry directly in the root, never a path.
    if (name !== path.basename(name) || name.startsWith('.') || versionFolder.test(name) || protectedNames.has(name.toLowerCase()) || /\.exe$/i.test(name)) continue;
    const target = path.join(root, name);
    let stat;
    try { stat = await fsp.lstat(target); } catch { continue; }
    if (stat.isDirectory() && !stat.isSymbolicLink()) { if (await retire(target, root, log) === 'kept') kept++; }
    else {
      try { await fsp.rm(target, { force: true }); } catch (error) { kept++; log(`Cleanup: kept ${target} for now (${error.code || error.message}).`); }
    }
  }
  if (kept) return 'kept';
  await fsp.rm(list, { force: true });
  log(`Cleanup: the old single-folder installation in ${root} is removed.`);
  return 'removed';
}

module.exports = { POINTER, COMPLETE, installerError, parseVersion, compareVersions, installRoot, isComplete, activeVersion, pendingVersion, cleanup };
