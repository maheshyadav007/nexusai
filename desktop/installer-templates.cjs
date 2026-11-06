const fs = require('node:fs/promises');
const path = require('node:path');

// electron-builder's install section runs the previous version's uninstaller and then unpacks over the
// installation folder. NexusAI installs each version beside the others instead (installer/installer.nsh),
// so those two steps are replaced. The exact text is pinned: a template change must be reviewed, never guessed.
const replacements = [
  [`!insertmacro uninstallOldVersion SHELL_CONTEXT
!insertmacro handleUninstallResult SHELL_CONTEXT

\${if} $installMode == "all"
  !insertmacro uninstallOldVersion HKEY_CURRENT_USER
  !insertmacro handleUninstallResult HKEY_CURRENT_USER
\${endIf}

SetOutPath $INSTDIR
`, `!insertmacro nxPrepareInstall
`],
  [`!insertmacro installApplicationFiles
`, `!insertmacro installApplicationFiles
!insertmacro nxActivateInstall
`],
];

function patchInstallSection(source) {
  let patched = source.replace(/\r\n/g, '\n');
  for (const [old, replacement] of replacements) {
    if (patched.split(old).length !== 2) throw new Error('The pinned NSIS install section changed. Review the side-by-side installation before building.');
    patched = patched.replace(old, replacement);
  }
  return patched;
}

// The previous version's uninstaller is no longer run, so its helper functions would be unused, and
// makensis treats unused functions as errors (-WX). Keep them out of the build.
function patchInstallUtil(source) {
  let patched = source.replace(/\r\n/g, '\n');
  for (const name of ['GetInQuotes', 'GetFileParent', 'handleUninstallResult', 'uninstallOldVersion']) {
    const start = patched.indexOf(`Function ${name}\n`);
    const end = start < 0 ? -1 : patched.indexOf('FunctionEnd\n', start);
    if (start < 0 || end < 0 || patched.indexOf(`Function ${name}\n`, start + 1) >= 0) {
      throw new Error('The pinned NSIS installUtil template changed. Review the side-by-side installation before building.');
    }
    patched = `${patched.slice(0, start)}!ifdef NX_RUN_PREVIOUS_UNINSTALLER\n${patched.slice(start, end)}FunctionEnd\n!endif\n${patched.slice(end + 'FunctionEnd\n'.length)}`;
  }
  return patched;
}

async function withInstallerTemplates(templates, build) {
  const files = { section: path.join(templates, 'installSection.nsh'), util: path.join(templates, 'include', 'installUtil.nsh') };
  const originals = {};
  for (const [key, file] of Object.entries(files)) originals[key] = await fs.readFile(file, 'utf8');
  const patched = { section: patchInstallSection(originals.section), util: patchInstallUtil(originals.util) };
  try {
    for (const [key, file] of Object.entries(files)) await fs.writeFile(file, patched[key]);
    return await build();
  } finally {
    for (const [key, file] of Object.entries(files)) await fs.writeFile(file, originals[key]);
  }
}

module.exports = { patchInstallSection, patchInstallUtil, withInstallerTemplates };
