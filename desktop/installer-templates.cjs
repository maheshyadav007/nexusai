const fs = require('node:fs/promises');

function patchUninstallMessage(source) {
  const old = 'MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(appCannotBeClosed)" /SD IDCANCEL IDRETRY OneMoreAttempt';
  if (!source.includes(old)) throw new Error('The pinned installer template changed. Review uninstall error handling before building.');
  return source.replace(old, 'MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "Could not remove the previous installation (uninstaller exit code $R0). A file may still be locked or access denied. No new version was installed. Close local services normally and inspect the installer details before retrying." /SD IDCANCEL IDRETRY OneMoreAttempt');
}

async function withInstallerTemplates(file, build) {
  const original = await fs.readFile(file, 'utf8');
  const patched = patchUninstallMessage(original);
  try { await fs.writeFile(file, patched); return await build(); }
  finally { await fs.writeFile(file, original); }
}
module.exports = { patchUninstallMessage, withInstallerTemplates };
