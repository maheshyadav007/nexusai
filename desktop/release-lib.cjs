const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const yaml = require('js-yaml');
const { UUID } = require('builder-util-runtime');

function validateConfig(config, publishing = false) {
  if (config.schemaVersion !== 1) throw new Error('Unsupported release configuration. Run init with the current example.');
  if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(config.version)) throw new Error('Version must be three numbers without leading zeroes, for example 0.1.0.');
  if (typeof config.signing?.enabled !== 'boolean') throw new Error('Set signing.enabled to true or false.');
  if (config.embedCredentials !== undefined && typeof config.embedCredentials !== 'boolean') throw new Error('embedCredentials must be true or false.');
  if (config.updateBaseUrl) {
    const url = new URL(config.updateBaseUrl);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || !url.pathname.endsWith('/windows/x64/')) {
      throw new Error('updateBaseUrl must be an HTTP(S) URL ending in /windows/x64/, without credentials, query or fragment.');
    }
  }
  if (config.signing?.enabled && (!config.signing.publisherName || !config.signing.certificateFile)) {
    throw new Error('Signed builds require signing.publisherName and signing.certificateFile.');
  }
  if (publishing && (!config.updateBaseUrl || !config.ssh?.host || !config.ssh.username)) {
    throw new Error('Set updateBaseUrl, ssh.host and ssh.username in desktop/release.local.json first.');
  }
  const server = config.server;
  if (!server || !/^\/[A-Za-z0-9_/-]+$/.test(server.root) || server.root.includes('..') || server.root === '/') {
    throw new Error('server.root must be a dedicated absolute Linux path, such as /srv/nexusai-updates.');
  }
  for (const port of [server.port, config.ssh?.port]) {
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('SSH and server ports must be numbers from 1 to 65535.');
  }
  for (const key of ['tlsCertificate', 'tlsKey']) {
    if (server[key] && (!/^\/[A-Za-z0-9_.\/-]+$/.test(server[key]) || server[key].includes('..'))) throw new Error(`Invalid server.${key} path.`);
  }
  if (!!server.tlsCertificate !== !!server.tlsKey) throw new Error('Set both server.tlsCertificate and server.tlsKey, or neither.');
  if (config.ssh && ('password' in config.ssh || 'passphrase' in config.ssh)) throw new Error('Do not save SSH passwords in configuration; use the interactive prompt.');
  return config;
}

function sha256(file) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(file);
    stream.on('error', reject); stream.on('data', (chunk) => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
  });
}

function safeName(name) {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$/.test(name)) throw new Error(`Invalid release filename: ${name}`);
  return name;
}

function makeChannelMetadata(raw, version, files) {
  const info = yaml.load(raw);
  if (!info || info.version !== version || !Array.isArray(info.files) || info.files.length !== 1) throw new Error('Unexpected generated update metadata.');
  const installer = files.find((file) => file.name.endsWith('.exe'));
  if (!installer) throw new Error('Installer missing from release.');
  if (info.files[0].url !== installer.name || (info.path && info.path !== installer.name)) throw new Error('Update metadata references a different installer.');
  info.files[0].url = `${version}/${installer.name}`;
  if (info.path) info.path = `${version}/${installer.name}`;
  return yaml.dump(info, { lineWidth: -1 });
}

async function verifyArtifacts(directory, manifest) {
  if (!/^\d+\.\d+\.\d+$/.test(manifest.version)) throw new Error('Invalid artifact version.');
  if (!Array.isArray(manifest.files) || manifest.files.length < 2) throw new Error('Incomplete release manifest.');
  const seen = new Set();
  for (const file of manifest.files) {
    safeName(file.name);
    if (seen.has(file.name)) throw new Error('Duplicate artifact filename.');
    seen.add(file.name);
    const target = path.join(directory, file.name);
    if (fs.statSync(target).size !== file.size || await sha256(target) !== file.sha256) throw new Error(`Artifact changed or corrupted: ${file.name}`);
  }
  if (!manifest.files.some((file) => file.name.endsWith('.exe')) || !seen.has('latest.yml')) throw new Error('Missing installer or update metadata.');
}

// Unused parts of the standard library and package test suites. Fewer files means a smaller download and
// less for security scanners to hold open.
const unusedPython = ['Lib/test', 'Lib/idlelib', 'Lib/tkinter', 'Lib/turtledemo', 'Lib/turtle.py', 'tcl',
  'DLLs/_tkinter.pyd', 'DLLs/tcl86t.dll', 'DLLs/tk86t.dll'];
function countFiles(target) {
  const stat = fs.lstatSync(target);
  if (!stat.isDirectory()) return 1;
  return fs.readdirSync(target).reduce((total, name) => total + countFiles(path.join(target, name)), 0);
}
async function trimPython(pythonRoot) {
  const targets = unusedPython.map((relative) => path.join(pythonRoot, relative)).filter((target) => fs.existsSync(target));
  const site = path.join(pythonRoot, 'Lib', 'site-packages');
  const walk = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const child = path.join(directory, entry.name);
      if (entry.name === 'tests' && directory !== site) targets.push(child); else walk(child);
    }
  };
  if (fs.existsSync(site)) walk(site);
  let removed = 0;
  for (const target of targets) { removed += countFiles(target); await fs.promises.rm(target, { recursive: true, force: true }); }
  return removed;
}

// Compiles installer/launcher.nsi with the makensis electron-builder uses.
async function compileLauncher({ productName, icon, outFile, run }) {
  const { getMakeNsisPath } = require('app-builder-lib/out/toolsets/windows');
  const makensis = await getMakeNsisPath(null);
  await fs.promises.mkdir(path.dirname(outFile), { recursive: true });
  await fs.promises.rm(outFile, { force: true });
  // LC_CTYPE: the macOS/Linux makensis builds abort on Unicode scripts without a UTF-8 character type.
  await run(makensis.path, ['-V2', '-WX', '-INPUTCHARSET', 'UTF8', `-DPRODUCT_NAME=${productName}`, `-DPRODUCT_EXE=${productName}.exe`, `-DICON=${icon}`,
    `-DOUTFILE=${outFile}`, path.join(__dirname, 'installer', 'launcher.nsi')], { env: { ...process.env, ...makensis.env, LC_CTYPE: 'UTF-8' } });
  if (!fs.existsSync(outFile)) throw new Error('The NexusAI launcher was not built.');
  return outFile;
}

function windowsBuilderConfig({ appId, productName, packageName, version, output, launcher, signed, signing, updateBaseUrl, setupName }) {
  return {
    appId, productName, asar: true,
    directories: { output, buildResources: 'build-resources' },
    files: ['main.cjs', 'runtime.cjs', 'layout.cjs', 'loading.html', 'shutdown.html', 'preload.cjs', 'build-resources/icon.png', 'build-resources/LICENSE.lucide', 'package.json'],
    extraResources: [{ from: 'resources', to: '.', filter: ['**/*'] },
      { from: 'frontend-server.cjs', to: 'frontend-server.cjs' },
      { from: 'installer/check-install.ps1', to: 'check-install.ps1' }],
    extraFiles: [{ from: launcher, to: 'nexusai-launcher.exe' }],
    extraMetadata: { name: packageName, version },
    artifactName: setupName,
    win: { icon: path.join(__dirname, 'build-resources', 'icon.ico'), target: [{ target: 'nsis', arch: ['x64'] }], verifyUpdateCodeSignature: signed,
      ...(signed ? { certificateFile: signing.certificateFile, publisherName: signing.publisherName } : {}) },
    nsis: { oneClick: false, perMachine: false, allowElevation: false, allowToChangeInstallationDirectory: true,
      guid: installationGuid(appId),
      include: path.join(__dirname, 'installer', 'installer.nsh'),
      deleteAppDataOnUninstall: false, createDesktopShortcut: true, runAfterFinish: true },
    forceCodeSigning: signed,
    ...(updateBaseUrl ? { publish: [{ provider: 'generic', url: updateBaseUrl }] } : {}),
  };
}

function quote(value) { return `'${String(value).replaceAll("'", "'\\''")}'`; }
function feedUrl(config, signed) { return new URL(signed ? './' : 'unsigned/', config.updateBaseUrl).href; }
function installationGuid(appId) { return UUID.v5(appId, UUID.parse('50e065bc-3134-11e6-9bab-38c9862bdaf3')); }

module.exports = { validateConfig, sha256, safeName, makeChannelMetadata, verifyArtifacts, quote, feedUrl, installationGuid, trimPython, compileLauncher,
  windowsBuilderConfig };
