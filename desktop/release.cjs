#!/usr/bin/env node
const fs = require('node:fs');
const fsp = fs.promises;
const path = require('node:path');
const os = require('node:os');
const { spawn, spawnSync } = require('node:child_process');
const { randomUUID } = require('node:crypto');
const yaml = require('js-yaml');
const lib = require('./release-lib.cjs');
const ssh = require('./ssh.cjs');
const profiles = require('./profiles.cjs');

const root = path.resolve(__dirname, '..');
const work = path.join(root, '.release');
const configFile = path.join(__dirname, 'release.local.json');
const pins = require('./toolchain.json');
const args = process.argv.slice(2);
const option = (name, fallback) => { const at = args.indexOf(`--${name}`); return at < 0 ? fallback : args[at + 1]; };
const channel = option('channel', 'pilot');
const uv = process.env.NEXUSAI_UV || 'uv';

function run(command, arguments_, options = {}) {
  console.log(`> ${path.basename(command)} ${arguments_.join(' ')}`);
  return new Promise((resolve, reject) => {
    const child = spawn(command, arguments_, { cwd: root, stdio: 'inherit', ...options });
    child.once('error', reject);
    child.once('exit', (code) => code === 0 ? resolve() : reject(new Error(`${path.basename(command)} failed (${code}).`)));
  });
}
function capture(command, arguments_, cwd = root) {
  const result = spawnSync(command, arguments_, { cwd, encoding: 'utf8', windowsHide: true });
  if (result.error || result.status !== 0) throw result.error || new Error(result.stderr || `${command} failed.`);
  return result.stdout.trim();
}
const npmCli = path.join(path.dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js');
function npm(arguments_, cwd, env = process.env) {
  const cli = fs.existsSync(npmCli) ? npmCli : process.env.NEXUSAI_NPM_CLI;
  if (!cli) throw new Error('Use desktop.cmd on Windows, or set NEXUSAI_NPM_CLI to npm-cli.js for developer checks.');
  return run(process.execPath, [cli, ...arguments_], { cwd, env });
}
function load() {
  if (!fs.existsSync(configFile)) throw new Error('Run desktop.cmd init first. Configuration stays local and is ignored by Git.');
  const config = lib.validateConfig(JSON.parse(fs.readFileSync(configFile, 'utf8').replace(/^\uFEFF/, '')));
  for (const [object, key] of [[config, 'companyEnvFile'], [config.signing, 'certificateFile'], [config.ssh, 'privateKeyFile']]) {
    if (object[key] && !path.isAbsolute(object[key])) object[key] = path.resolve(__dirname, object[key]);
  }
  return config;
}
function save(config) { fs.writeFileSync(configFile, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o600 }); }
function windows() { if (process.platform !== 'win32' || process.arch !== 'x64') throw new Error('Build/test commands require Windows x64. Linux hosts the files; develop on your Mac as usual.'); }

async function init() {
  if (!fs.existsSync(configFile)) fs.copyFileSync(path.join(__dirname, 'release.example.json'), configFile);
  const config = load();
  console.log('Local installer builds work without a server. Leave hosting fields blank to configure them later.');
  config.updateBaseUrl = await ssh.ask('Update URL, ending in /windows/x64/ (blank = local build only)', config.updateBaseUrl);
  config.ssh.host = await ssh.ask('Linux SSH host (blank = configure later)', config.ssh.host);
  if (config.ssh.host) {
    config.ssh.username = await ssh.ask('Linux SSH username', config.ssh.username);
    config.ssh.port = Number(await ssh.ask('SSH port', String(config.ssh.port)));
    config.ssh.privateKeyFile = await ssh.ask('SSH private key file (blank = prompt for password)', config.ssh.privateKeyFile);
  }
  lib.validateConfig(config); save(config);
  console.log(`Saved ${configFile}\nNext: desktop.cmd build (local test), or desktop.cmd server-setup (configure Linux hosting).`);
}

function doctor(config) {
  console.log(`OS: ${process.platform}/${process.arch}; Node: ${process.version}; pinned Python: ${pins.python}`);
  console.log(`Git: ${capture('git', ['--version'])}`);
  console.log(`uv: ${capture(uv, ['--version'])}`);
  console.log(`Update feed: ${config.updateBaseUrl || '(disabled for this local build)'}`);
  console.log(`Signing: ${config.signing.enabled ? config.signing.publisherName : 'unsigned pilot; separate app and data directory'}`);
  if (config.signing.enabled && !fs.existsSync(config.signing.certificateFile)) throw new Error('Signing certificate file not found.');
  if (!config.updateBaseUrl) console.log('Set an update URL BEFORE building an app intended to receive automatic updates.');
}

async function snapshot(destination) {
  await fsp.mkdir(destination, { recursive: true });
  // Only tracked application files enter the build. Never copy .env, local Homes or node_modules.
  const listed = capture('git', ['ls-files', '-z', '--', 'frontend', 'backend']).split('\0').filter(Boolean);
  if (!listed.length) throw new Error('No tracked application source found. Run from a Git checkout.');
  for (const relative of listed) {
    if (relative.split('/').some((part) => part === '.env' || part.startsWith('.env.'))) continue;
    const target = path.join(destination, relative);
    await fsp.mkdir(path.dirname(target), { recursive: true });
    await fsp.copyFile(path.join(root, relative), target);
  }
}

function artifactDirectory(config, version = config.version) {
  return path.join(work, 'artifacts', config.ciProbe ? 'ci' : config.signing.enabled ? 'signed' : 'unsigned', version);
}

async function build(config) {
  windows(); doctor(config);
  await run(process.execPath, ['--test', path.join(__dirname, 'tests/release.test.cjs'), path.join(__dirname, 'tests/profiles.test.cjs')]);
  const dirty = capture('git', ['status', '--porcelain', '--untracked-files=normal', '--', 'frontend', 'backend', 'desktop', 'scripts/desktop.ps1', 'desktop.cmd']);
  if (dirty) throw new Error('Commit the application and release tooling before building. Machine-local ignored configuration is allowed.');
  const explicitVersion = option('version', null);
  let version = explicitVersion || config.version;
  if (!explicitVersion && fs.existsSync(path.join(artifactDirectory(config, version), 'release.json'))) {
    const parts = version.split('.').map(Number); parts[2] += 1; version = parts.join('.');
  }
  lib.validateConfig({ ...config, version });
  const output = artifactDirectory(config, version);
  if (fs.existsSync(path.join(output, 'release.json'))) throw new Error(`Version ${version} already exists locally. Choose a new version; use publish to upload an existing build.`);
  const buildRoot = path.join(work, 'build');
  const resources = path.join(__dirname, 'resources');
  await fsp.rm(buildRoot, { recursive: true, force: true });
  await fsp.rm(resources, { recursive: true, force: true });
  await fsp.rm(output, { recursive: true, force: true });
  await fsp.mkdir(resources, { recursive: true });
  const deployment = config.companyEnvFile ? await fsp.readFile(config.companyEnvFile, 'utf8') : '';
  await fsp.writeFile(path.join(resources, 'deployment.env'), profiles.deploymentDefaults(deployment, config.embedCredentials === true));
  await snapshot(buildRoot);
  const backendRoot = path.join(buildRoot, 'backend');
  const frontendRoot = path.join(buildRoot, 'frontend');
  await run(uv, ['python', 'install', pins.python, '--no-bin', '--no-registry']);
  const sourcePython = capture(uv, ['python', 'find', '--managed-python', pins.python]);
  await run(uv, ['run', '--locked', '--python', sourcePython, 'pytest', '-q', 'tests/test_desktop.py', 'tests/test_api.py'], { cwd: backendRoot });
  const pythonRoot = path.join(resources, 'python');
  await fsp.cp(path.dirname(sourcePython), pythonRoot, { recursive: true, dereference: true });
  const python = path.join(pythonRoot, 'python.exe');
  const site = path.join(pythonRoot, 'Lib', 'site-packages');
  const requirements = path.join(buildRoot, 'requirements.txt');
  await run(uv, ['export', '--locked', '--no-dev', '--no-emit-project', '--no-editable', '--output-file', requirements], { cwd: backendRoot });
  await run(uv, ['pip', 'install', '--python', python, '--target', site, '--require-hashes', '--only-binary', ':all:', '-r', requirements]);
  const wheels = path.join(buildRoot, 'wheels');
  await run(uv, ['build', '--wheel', '--python', python, '--out-dir', wheels], { cwd: backendRoot });
  const wheel = (await fsp.readdir(wheels)).find((file) => file.endsWith('.whl'));
  if (!wheel) throw new Error('Backend wheel was not produced.');
  await run(uv, ['pip', 'install', '--python', python, '--target', site, '--no-deps', path.join(wheels, wheel)]);
  await run(python, ['-c', 'import sqlcipher3, pypff, cryptography, onnxruntime, tokenizers; from zoneinfo import ZoneInfo, reset_tzpath; reset_tzpath([]); [ZoneInfo(z) for z in ("UTC", "Asia/Kolkata", "America/New_York")]; from nexusai.kernel.config import load_config; from nexusai.api.desktop import DesktopControl; c=sqlcipher3.connect(":memory:"); c.execute("PRAGMA key=\'smoke\'"); assert c.execute("PRAGMA cipher_version").fetchone(); load_config(); print("Bundled native dependencies and backend imports OK")']);
  await fsp.mkdir(path.join(resources, 'node'), { recursive: true });
  await fsp.copyFile(process.execPath, path.join(resources, 'node', 'node.exe'));
  const env = { ...process.env, NEXUSAI_DESKTOP_BUILD: '1', NODE_ENV: 'production' };
  await npm(['ci', '--include=dev', '--no-audit', '--no-fund'], frontendRoot, env);
  await npm(['run', 'check'], frontendRoot, { ...env, NODE_ENV: 'test' });
  await npm(['run', 'build'], frontendRoot, env);
  const standalone = path.join(frontendRoot, '.next', 'standalone');
  const frontResources = path.join(resources, 'frontend');
  await fsp.cp(standalone, frontResources, { recursive: true, dereference: true });
  if (!fs.existsSync(path.join(frontResources, 'server.js'))) throw new Error('Unexpected Next.js standalone layout: server.js is missing.');
  await fsp.cp(path.join(frontendRoot, '.next', 'static'), path.join(frontResources, '.next', 'static'), { recursive: true });
  if (fs.existsSync(path.join(frontendRoot, 'public'))) await fsp.cp(path.join(frontendRoot, 'public'), path.join(frontResources, 'public'), { recursive: true });
  const signed = config.signing.enabled;
  const productName = config.ciProbe ? 'NexusAI CI' : signed ? 'NexusAI' : 'NexusAI Pilot';
  const runtime = { appId: config.ciProbe ? 'com.nexusai.ci' : signed ? 'com.nexusai.desktop' : 'com.nexusai.pilot',
    ciProbe: config.ciProbe === true, dataDirectory: productName, signed,
    updateBaseUrl: config.updateBaseUrl ? lib.feedUrl(config, signed) : '' };
  await fsp.writeFile(path.join(resources, 'runtime.json'), JSON.stringify(runtime, null, 2));
  const builder = {
    appId: runtime.appId, productName, asar: true,
    directories: { output, buildResources: 'build-resources' },
    files: ['main.cjs', 'runtime.cjs', 'loading.html', 'package.json'],
    extraResources: [{ from: 'resources', to: '.', filter: ['**/*'] },
      { from: 'frontend-server.cjs', to: 'frontend-server.cjs' }],
    extraMetadata: { name: config.ciProbe ? 'nexusai-ci' : signed ? 'nexusai' : 'nexusai-pilot', version },
    artifactName: `NexusAI${config.ciProbe ? '-CI' : signed ? '' : '-Pilot'}-Setup-${version}.exe`,
    win: { target: [{ target: 'nsis', arch: ['x64'] }], verifyUpdateCodeSignature: signed,
      ...(signed ? { certificateFile: config.signing.certificateFile, publisherName: config.signing.publisherName } : {}) },
    nsis: { oneClick: false, perMachine: false, allowElevation: false, allowToChangeInstallationDirectory: true,
      deleteAppDataOnUninstall: false, createDesktopShortcut: true, runAfterFinish: false },
    forceCodeSigning: signed,
    ...(runtime.updateBaseUrl ? { publish: [{ provider: 'generic', url: runtime.updateBaseUrl }] } : {}),
  };
  const builderConfig = path.join(work, 'builder.json');
  await fsp.writeFile(builderConfig, JSON.stringify(builder, null, 2));
  const signingEnv = { ...process.env, CSC_IDENTITY_AUTO_DISCOVERY: signed ? 'true' : 'false' };
  if (signed && !signingEnv.CSC_KEY_PASSWORD) signingEnv.CSC_KEY_PASSWORD = await ssh.secret('Code-signing certificate password');
  await run(process.execPath, [path.join(__dirname, 'node_modules/electron-builder/out/cli/cli.js'),
    '--win', 'nsis', '--x64', '--config', builderConfig, '--publish', 'never'], { cwd: __dirname, env: signingEnv });
  if (!runtime.updateBaseUrl) {
    // Local-only builds still get a manifest for install/smoke testing; they cannot be published.
    await fsp.writeFile(path.join(output, 'latest.yml'), yaml.dump({ version, files: [] }));
  }
  const files = [];
  for (const name of (await fsp.readdir(output)).filter((file) => /\.(exe|blockmap)$/.test(file) || file === 'latest.yml')) {
    lib.safeName(name); const file = path.join(output, name);
    files.push({ name, size: (await fsp.stat(file)).size, sha256: await lib.sha256(file) });
  }
  const manifest = { schemaVersion: 1, version, signed, ciProbe: runtime.ciProbe, appId: runtime.appId, productName,
    sourceCommit: capture('git', ['rev-parse', 'HEAD']), updateBaseUrl: runtime.updateBaseUrl,
    toolchain: { ...pins, electron: require('./package.json').devDependencies.electron }, files };
  if (runtime.updateBaseUrl) {
    const metadata = lib.makeChannelMetadata(await fsp.readFile(path.join(output, 'latest.yml'), 'utf8'), version, files);
    manifest.channelSha256 = require('node:crypto').createHash('sha256').update(metadata).digest('hex');
  }
  await fsp.writeFile(path.join(output, 'release.json'), JSON.stringify(manifest, null, 2));
  await lib.verifyArtifacts(output, manifest);
  config.version = version; save(config);
  console.log(`Built ${version}: ${output}\nNext: desktop.cmd test. No files have been published.`);
  return output;
}

async function test(config, install = false) {
  windows();
  const version = option('version', config.version);
  const directory = artifactDirectory(config, version);
  const manifest = JSON.parse(await fsp.readFile(path.join(directory, 'release.json'), 'utf8'));
  await lib.verifyArtifacts(directory, manifest);
  const installer = manifest.files.find((file) => file.name.endsWith('.exe'));
  const testInstall = path.join(process.env.LOCALAPPDATA || os.tmpdir(), `NexusAI-Pipeline-${manifest.ciProbe ? 'CI' : manifest.signed ? 'Signed' : 'Pilot'}`);
  if (install && manifest.signed && fs.existsSync(path.join(process.env.APPDATA || os.homedir(), 'NexusAI', 'home-pointer.json'))) {
    throw new Error('Run signed installer tests in a disposable Windows account/VM. This account already has a NexusAI Home.');
  }
  const executable = path.join(install ? testInstall : path.join(directory, 'win-unpacked'), `${manifest.productName}.exe`);
  if (install) {
    const active = capture('powershell.exe', ['-NoProfile', '-Command',
      `$target = '${manifest.productName.replaceAll("'", "''")}'; @(Get-Process | Where-Object { $_.ProcessName -eq $target }).Count`]);
    if (Number(active) > 0) throw new Error('Close NexusAI normally before an installer test. Active work will not be force-stopped.');
    // Installer tests change Windows registration for this app ID. Use a disposable account for signed tests.
    await run(path.join(directory, installer.name), ['/S', `/D=${testInstall}`]);
  }
  if (!fs.existsSync(executable)) throw new Error(`Installer did not create ${executable}. Inspect the installer log and rerun test.`);
  const smoke = path.join(work, 'smoke', `${version}-${Date.now()}`);
  await fsp.mkdir(smoke, { recursive: true });
  await run(executable, ['--smoke-dir', smoke], { timeout: 180000 });
  const result = JSON.parse(await fsp.readFile(path.join(smoke, 'result.json'), 'utf8'));
  if (!result.ok || result.version !== version) throw new Error(`Installed app smoke test failed. See ${smoke}`);
  const report = { ...result, testedAt: new Date().toISOString(), sourceCommit: manifest.sourceCommit,
    releaseSha256: await lib.sha256(path.join(directory, 'release.json')), kind: install ? 'installed' : 'packaged',
    screenshot: path.join(smoke, 'window.png') };
  await fsp.writeFile(path.join(directory, 'smoke.json'), JSON.stringify(report, null, 2));
  console.log(`${install ? 'Installed' : 'Packaged'}-app smoke passed. Review the screenshot: ${report.screenshot}\nThis does not certify real mailbox operations or an A-to-B update.`);
}

async function openApp(config) {
  windows();
  const productName = config.signing.enabled ? 'NexusAI' : 'NexusAI Pilot';
  const executable = path.join(process.env.LOCALAPPDATA || os.tmpdir(), `NexusAI-Pipeline-${config.signing.enabled ? 'Signed' : 'Pilot'}`, `${productName}.exe`);
  if (!fs.existsSync(executable)) throw new Error('Run desktop.cmd build-test first.');
  if (config.companyEnvFile) {
    const data = path.join(process.env.APPDATA, productName);
    await fsp.mkdir(data, { recursive: true });
    await fsp.copyFile(config.companyEnvFile, path.join(data, 'company.env'));
  }
  const child = spawn(executable, [], { detached: true, stdio: 'ignore' });
  child.on('error', (error) => console.error(error.message)); child.unref();
  console.log(`Opened ${productName}. Use a disposable Home for the first mail/agent checks.`);
}

async function serverSetup(config) {
  lib.validateConfig(config, true);
  const connection = await ssh.connect(config.ssh, work);
  let session;
  const temporary = `/tmp/nexusai-setup-${randomUUID()}`;
  try {
    session = await ssh.sftp(connection);
    await ssh.exec(connection, `mkdir -m 700 -- ${lib.quote(temporary)}`);
    const remote = `${temporary}/setup.sh`;
    await ssh.put(session, path.join(__dirname, 'linux/setup.sh'), remote);
    const parameters = [config.server.root, config.ssh.username, config.server.port, config.server.tlsCertificate, config.server.tlsKey].map(lib.quote).join(' ');
    const command = `bash ${lib.quote(remote)} ${parameters}`;
    if (config.ssh.username === 'root') await ssh.exec(connection, command);
    else {
      console.log('One-time setup installs/configures Nginx and Python and needs Linux sudo rights.');
      const password = await ssh.secret('Linux sudo password (blank if passwordless sudo)');
      await ssh.exec(connection, `${password ? "sudo -S -p ''" : 'sudo -n'} -- ${command}`, password ? `${password}\n` : '');
    }
    console.log(`Configured. Download base should be ${config.updateBaseUrl}. The first publish verifies public downloads.`);
  } finally {
    try { await ssh.exec(connection, `rm -rf -- ${lib.quote(temporary)}`); } catch { /* Preserve original failure. */ }
    session?.end(); connection.end();
  }
}

async function publish(config) {
  lib.validateConfig(config, true);
  if (!['pilot', 'stable'].includes(channel)) throw new Error('Channel must be pilot or stable.');
  const directory = artifactDirectory(config, option('version', config.version));
  const manifest = JSON.parse(await fsp.readFile(path.join(directory, 'release.json'), 'utf8'));
  await lib.verifyArtifacts(directory, manifest);
  if (manifest.updateBaseUrl !== lib.feedUrl(config, manifest.signed)) throw new Error('The update URL changed since this installer was built. Rebuild with a new version.');
  if (channel === 'stable' && (!manifest.signed || !manifest.updateBaseUrl.startsWith('https://'))) throw new Error('Stable publication requires a signed installer and HTTPS. Unsigned internal testing uses pilot.');
  const report = JSON.parse(await fsp.readFile(path.join(directory, 'smoke.json'), 'utf8'));
  if (!report.ok || report.releaseSha256 !== await lib.sha256(path.join(directory, 'release.json'))) throw new Error('Run desktop.cmd test for these exact artifacts before publication.');
  if (channel === 'stable' && await ssh.ask('Have you verified a real update and mail workflow on the company laptop? Type yes', 'no') !== 'yes') throw new Error('Stable promotion cancelled.');
  const metadata = lib.makeChannelMetadata(await fsp.readFile(path.join(directory, 'latest.yml'), 'utf8'), manifest.version, manifest.files);
  const localMeta = path.join(work, 'channel.yml');
  await fsp.writeFile(localMeta, metadata);
  const connection = await ssh.connect(config.ssh, work);
  let session;
  const remoteRoot = `${config.server.root}/windows/x64${manifest.signed ? '' : '/unsigned'}`;
  const remoteStage = `${remoteRoot}/.incoming/${randomUUID()}`;
  try {
    await ssh.exec(connection, `mkdir -m 700 -- ${lib.quote(remoteStage)}`);
    session = await ssh.sftp(connection);
    for (const file of [...manifest.files, { name: 'release.json' }]) {
      console.log(`Uploading ${file.name}`);
      await ssh.put(session, path.join(directory, file.name), `${remoteStage}/${file.name}`);
    }
    await ssh.put(session, localMeta, `${remoteStage}/channel.yml`);
    await ssh.put(session, path.join(__dirname, 'linux/publish.py'), `${remoteStage}/publish.py`);
    await ssh.exec(connection, `python3 ${lib.quote(`${remoteStage}/publish.py`)} ${lib.quote(remoteRoot)} ${lib.quote(remoteStage)} ${lib.quote(channel === 'stable' ? 'latest' : 'pilot')}`);
    const publicUrl = new URL(channel === 'stable' ? 'latest.yml' : 'pilot.yml', manifest.updateBaseUrl);
    const response = await fetch(publicUrl, { cache: 'no-store', signal: AbortSignal.timeout(15000) });
    if (!response.ok || yaml.load(await response.text())?.version !== manifest.version) throw new Error('Publication completed on disk, but the HTTP manifest check failed. Check Nginx, the URL and network access. Do not rebuild; retry publish after fixing hosting.');
    const installer = manifest.files.find((file) => file.name.endsWith('.exe'));
    const download = new URL(`${manifest.version}/${installer.name}`, manifest.updateBaseUrl);
    const head = await fetch(download, { method: 'HEAD', signal: AbortSignal.timeout(15000) });
    if (!head.ok || Number(head.headers.get('content-length')) !== installer.size) throw new Error('Published installer is not downloadable with the expected size. Check hosting before distributing.');
    console.log(`Published and HTTP-verified: ${download.href}\nExisting ${channel} clients will discover this version. Other users install it once from this URL.`);
  } finally {
    try { await ssh.exec(connection, `rm -rf -- ${lib.quote(remoteStage)}`); } catch { /* Already moved on successful publication. */ }
    session?.end(); connection.end();
  }
}

async function main() {
  await fsp.mkdir(work, { recursive: true });
  let action = args[0] || 'menu';
  if (action === 'ci-trigger') {
    const dirty = capture('git', ['status', '--porcelain', '--', 'frontend', 'backend', 'desktop', 'scripts', '.github', 'desktop.cmd', 'desktop.sh']);
    if (dirty) throw new Error('Commit the application, scripts and workflow before triggering CI. Local ignored deployment profiles are allowed.');
    const tag = `desktop-ci/${new Date().toISOString().replace(/[:.]/g, '-')}`;
    await run('git', ['tag', tag]);
    await run('git', ['push', 'origin', tag]);
    console.log(`Windows validation requested for ${tag}. Open the repository Actions tab for progress and downloadable artifacts.`);
    return;
  }
  const profilePath = path.resolve(root, option('profile', path.join(work, 'profile')));
  if (action === 'profile-init') return profiles.initProfile(root, profilePath);
  if (action === 'prepare-profile') {
    const archive = path.join(work, 'deployment.zip');
    profiles.prepareProfile(profilePath, archive, capture('git', ['rev-parse', 'HEAD']));
    return profiles.applyProfile(archive, path.join(work, 'deployment'), configFile);
  }
  if (action === 'apply-profile') return profiles.applyProfile(path.resolve(root, option('profile', path.join(work, 'deployment.zip'))), path.join(work, 'deployment'), configFile);
  if (action === 'ci') { windows(); return require('./ci.cjs')({ root, work, configFile, build, test, run }); }
  if (action === 'menu') {
    console.log('NexusAI desktop\n1. Local configuration\n2. Build + install/smoke test + open app\n3. Set up Linux host\n4. Build + test + publish to pilot\n5. Publish existing tested build\n6. Diagnose setup\n7. Open installed test app');
    action = ({ 1: 'init', 2: 'build-test', 3: 'server-setup', 4: 'release', 5: 'publish', 6: 'doctor', 7: 'open' })[await ssh.ask('Choose', '2')];
  }
  if (action === 'init') return init();
  const config = load();
  switch (action) {
    case 'doctor': return doctor(config);
    case 'build': return build(config);
    case 'test': return test(config);
    case 'install-test': return test(config, true);
    case 'build-test': await build(config); await test(config, true); return openApp(config);
    case 'open': return openApp(config);
    case 'server-setup': return serverSetup(config);
    case 'publish': return publish(config);
    case 'release':
      lib.validateConfig(config, true); await build(config); await test(config); return publish(config);
    default: throw new Error('Commands: init, doctor, build, test, install-test, build-test, open, server-setup, publish, release.');
  }
}

main().catch((error) => { console.error(`\nNexusAI release failed: ${error.stack}\nSee docs/WINDOWS_RELEASE_GUIDE.md. Nothing is promoted until artifact validation succeeds.`); process.exitCode = 1; });
