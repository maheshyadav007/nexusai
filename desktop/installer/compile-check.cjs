#!/usr/bin/env node
// Compiles the launcher and the complete NSIS installer and uninstaller from a stand-in app folder, with
// warnings as errors, on any OS. Catches script errors without a Windows build. Usage: npm run check:installer
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const lib = require('../release-lib.cjs');
const { withInstallerTemplates } = require('../installer-templates.cjs');

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: 'inherit', ...options });
    child.once('error', reject);
    child.once('exit', code => code === 0 ? resolve() : reject(new Error(`${path.basename(command)} failed (${code}).`)));
  });
}

async function main() {
  const desktop = path.resolve(__dirname, '..');
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'nexusai-installer-'));
  try {
    const productName = 'NexusAI Beta';
    const launcher = await lib.compileLauncher({ productName, icon: path.join(desktop, 'build-resources', 'icon.ico'),
      outFile: path.join(work, 'nexusai-launcher.exe'), run });
    const app = path.join(work, 'win-unpacked');
    fs.mkdirSync(path.join(app, 'resources'), { recursive: true });
    fs.copyFileSync(launcher, path.join(app, `${productName}.exe`));
    fs.copyFileSync(launcher, path.join(app, 'nexusai-launcher.exe'));
    fs.writeFileSync(path.join(app, 'resources', 'app.asar'), 'stand-in');
    const config = lib.windowsBuilderConfig({ appId: 'com.nexusai.pilot', productName, packageName: 'nexusai-pilot', version: '0.2.0',
      output: path.join(work, 'out'), launcher, signed: false, signing: {}, updateBaseUrl: 'https://updates.invalid/windows/x64/unsigned/',
      setupName: 'NexusAI-Beta-Setup-0.2.0.exe' });
    // The stand-in executable is not a real Electron binary; skip icon/resource editing.
    config.win = { ...config.win, signAndEditExecutable: false };
    config.forceCodeSigning = false;
    const { build, Platform, Arch } = require('electron-builder');
    process.env.LC_CTYPE = 'UTF-8';
    await withInstallerTemplates(path.join(desktop, 'node_modules/app-builder-lib/templates/nsis'), () => build({
      projectDir: desktop, prepackaged: app, config, publish: 'never', targets: Platform.WINDOWS.createTarget('nsis', Arch.x64),
    }));
    const setup = path.join(work, 'out', 'NexusAI-Beta-Setup-0.2.0.exe');
    if (!fs.existsSync(setup)) throw new Error('The installer was not produced.');
    console.log(`Launcher, installer and uninstaller compiled (${Math.round(fs.statSync(setup).size / 1024)} KB).`);
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
}

main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
