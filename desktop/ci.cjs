const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { spawn, spawnSync } = require('node:child_process');
const { randomUUID } = require('node:crypto');
const { once } = require('node:events');
const lib = require('./release-lib.cjs');
const { isAlive, waitExit } = require('./runtime.cjs');

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

module.exports = async function ci({ work, configFile, build, test, run, betaVersion = null }) {
  const previous = fs.existsSync(configFile) ? fs.readFileSync(configFile) : null;
  const config = structuredClone(require('./release.example.json'));
  // Only a fresh hosted runner may exercise the actual Beta registry identity.
  const acceptance = process.env.GITHUB_ACTIONS === 'true';
  const product = acceptance ? 'NexusAI Beta' : 'NexusAI CI';
  const appId = acceptance ? 'com.nexusai.pilot' : 'com.nexusai.ci';
  const guid = lib.installationGuid(appId);
  const ciRoot = path.join(work, 'ci');
  const feedRoot = path.join(ciRoot, 'feed');
  const defaultData = path.join(process.env.APPDATA, acceptance ? 'NexusAI Pilot' : 'NexusAI CI');
  const flag = path.join(defaultData, 'update-probe.json');
  const installed = path.join(process.env.LOCALAPPDATA, `NexusAI-Pipeline-${acceptance ? 'Beta-Acceptance' : 'CI'}`);
  const launcher = path.join(installed, `${product}.exe`);
  const uninstaller = path.join(installed, `Uninstall ${product}.exe`);
  const versionExe = version => path.join(installed, `app-${version}`, `${product}.exe`);
  const check = path.join(__dirname, 'installer/check-install.ps1');
  // Versions above the last single-folder Beta (0.1.0), so its installation can be converted in acceptance.
  const [from, to] = ['0.1.1', '0.1.2'];
  if (fs.existsSync(flag)) throw new Error('An earlier update probe is still registered. Inspect its running app before starting a fresh probe.');
  if (acceptance) {
    if (fs.existsSync(defaultData)) throw new Error('Beta acceptance requires a disposable Windows account without existing Beta data.');
    await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', `if ((Test-Path 'HKCU:\\Software\\${guid}') -or (Test-Path 'HKLM:\\Software\\${guid}')) { throw 'An existing Beta installation must not be replaced by acceptance tests.' }`]);
  }
  await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', path.join(__dirname, 'tests/installer.test.ps1')]);
  fs.mkdirSync(feedRoot, { recursive: true });
  const server = http.createServer((request, response) => {
    try {
      const relative = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
      const file = path.resolve(feedRoot, `.${relative}`);
      if (!file.startsWith(feedRoot + path.sep) || !fs.statSync(file).isFile()) { response.writeHead(404).end(); return; }
      response.writeHead(200, { 'content-length': fs.statSync(file).size, 'cache-control': 'no-store' });
      if (request.method === 'HEAD') response.end(); else fs.createReadStream(file).pipe(response);
    } catch { response.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  config.updateBaseUrl = `http://127.0.0.1:${server.address().port}/windows/x64/`;
  config.ciProbe = !acceptance;
  config.acceptanceProbe = acceptance;
  config.companyEnvFile = '';
  config.embedCredentials = false;
  config.version = from;
  const installerOf = directory => {
    const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'release.json'), 'utf8'));
    return path.join(directory, manifest.files.find(file => file.name.endsWith('.exe')).name);
  };
  const exitCode = (command, args) => new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: 'inherit', windowsHide: true });
    child.once('error', reject); child.once('exit', code => resolve(code));
  });
  const powershell = script => run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], { timeout: 200000 });
  const quoted = value => value.replaceAll("'", "''");
  const waitFile = async (file, timeout = 360000) => {
    const deadline = Date.now() + timeout;
    while (!fs.existsSync(file) && Date.now() < deadline) await delay(500);
    if (!fs.existsSync(file)) throw new Error(`Expected ${file}. Inspect desktop.log and %TEMP%\\nexusai-setup.log.`);
  };
  // Restarts go through the launcher, so the new version is not our child: wait for every installed process.
  const waitStopped = (folder = installed) => run('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', check,
    '-InstallDirectory', folder, '-AppGuid', guid, '-Version', to, '-Mode', 'uninstall', '-TimeoutSeconds', '180'], { timeout: 200000 });
  const uninstall = async (args = []) => {
    await run(uninstaller, ['/S', ...args], { timeout: 180000 });
    // NSIS's launcher can exit before its temporary uninstaller finishes.
    await powershell(`
      $deadline = (Get-Date).AddSeconds(120)
      while ((Test-Path -LiteralPath 'HKCU:\\Software\\${guid}') -or (Test-Path -LiteralPath '${quoted(launcher)}')) {
        if ((Get-Date) -ge $deadline) { throw 'Uninstall did not finish removing the registration and launcher.' }
        Start-Sleep -Milliseconds 250
      }`);
  };
  const probe = async (plan, during = async () => {}, folder = installed) => {
    const probeRoot = path.join(ciRoot, plan.mode);
    fs.mkdirSync(probeRoot, { recursive: true });
    fs.writeFileSync(path.join(probeRoot, 'plan.json'), JSON.stringify(plan));
    fs.mkdirSync(defaultData, { recursive: true });
    fs.writeFileSync(flag, JSON.stringify({ directory: probeRoot }));
    await during(probeRoot);
    const resultFile = path.join(probeRoot, 'result.json');
    await waitFile(resultFile);
    const result = JSON.parse(fs.readFileSync(resultFile, 'utf8'));
    await waitStopped(folder);
    fs.rmSync(flag, { force: true });
    if (!result.ok || result.to !== plan.to) throw new Error(`${plan.mode} upgrade failed: ${JSON.stringify(result)}`);
    return result;
  };
  const startFrom = (version) => { const child = spawn(versionExe(version), [], { stdio: 'inherit' }); child.on('error', error => console.error(error)); return child; };
  let lock = null;
  try {
    console.log(`Testing ${product}: side-by-side install, automatic and manual updates, locked files, launcher recovery and uninstall, with synthetic data and a loopback feed.`);
    const a = await build(config);
    await test(config, true);
    config.version = to;
    const b = await build(config);
    await test(config);
    const manifest = JSON.parse(fs.readFileSync(path.join(b, 'release.json'), 'utf8'));
    const feed = path.join(feedRoot, 'windows/x64/unsigned');
    const immutable = path.join(feed, manifest.version);
    fs.mkdirSync(immutable, { recursive: true });
    for (const file of manifest.files) fs.copyFileSync(path.join(b, file.name), path.join(immutable, file.name));
    fs.writeFileSync(path.join(feed, 'pilot.yml'), lib.makeChannelMetadata(fs.readFileSync(path.join(b, 'latest.yml'), 'utf8'), manifest.version, manifest.files));
    const results = {};
    const plan = mode => ({ mode, from, to, nonce: randomUUID() });

    // 1. Automatic update while a scanner-like process holds a file of the running version open without
    //    delete sharing: B is installed beside A, A restarts into B, and A's folder stays until it is free.
    // A file NexusAI itself never reads, so only the "scanner" holds it.
    const held = path.join(installed, `app-${from}`, 'LICENSES.chromium.html');
    lock = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
      `$s = [IO.File]::Open('${quoted(held)}', 'Open', 'Read', 'None'); Write-Output locked; Start-Sleep -Seconds 900`], { stdio: ['ignore', 'pipe', 'inherit'] });
    await new Promise((resolve, reject) => {
      lock.stdout.on('data', chunk => { if (String(chunk).includes('locked')) resolve(); });
      lock.once('exit', code => reject(new Error(`Could not hold ${held} open (${code}).`)));
    });
    results.automatic = await probe({ ...plan('automatic'), oldLocked: true }, async () => { startFrom(from); });
    if (results.automatic.oldVersion !== 'kept' || !fs.existsSync(versionExe(to))) throw new Error('A locked old file must not block the update and must keep its folder.');
    lock.kill(); await waitExit(lock, 10000).catch(() => {}); lock = null;

    // 2. An older installer must not take over.
    if (await exitCode(installerOf(a), ['/S', `/D=${installed}`]) !== 12) throw new Error('The installer allowed a downgrade or failed with an unexpected code.');

    // 3. Launcher recovery: a damaged version pointer still starts the newest complete version.
    const pointer = path.join(installed, 'nexusai-install.ini');
    const goodPointer = fs.readFileSync(pointer);
    fs.writeFileSync(pointer, '[Install]\r\nCurrent=..\\..\\Windows\r\n');
    const recovery = path.join(ciRoot, 'launcher-recovery');
    fs.mkdirSync(recovery, { recursive: true });
    await run(launcher, ['--smoke-dir', recovery], { timeout: 60000 });
    await waitFile(path.join(recovery, 'result.json'), 240000);
    const started = JSON.parse(fs.readFileSync(path.join(recovery, 'result.json'), 'utf8')).version;
    fs.writeFileSync(pointer, goodPointer);
    if (started !== to) throw new Error(`With a damaged pointer the launcher started ${started}, not ${to}.`);
    await waitStopped();

    // 4. A restart refuses while a bundled Python still runs; an unrelated process is left alone.
    const orphan = spawn(path.join(installed, `app-${to}`, 'resources/python/python.exe'), ['-c', 'import time; time.sleep(300)'], { stdio: 'ignore' });
    const unrelated = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' });
    try {
      await Promise.all([once(orphan, 'spawn'), once(unrelated, 'spawn')]);
      const code = await exitCode('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', check,
        '-InstallDirectory', installed, '-AppGuid', guid, '-Version', to, '-Mode', 'uninstall', '-TimeoutSeconds', '1']);
      if (code !== 10 || !isAlive(orphan) || !isAlive(unrelated)) throw new Error('Orphan/unrelated-process safety check failed.');
    } finally {
      // These two fixture PIDs were created by this test, not discovered by image name.
      if (isAlive(orphan)) orphan.kill();
      if (isAlive(unrelated)) unrelated.kill();
      await Promise.allSettled([waitExit(orphan, 10000), waitExit(unrelated, 10000)]);
    }

    // 5. A default uninstall keeps the user's data.
    await uninstall();
    if (!fs.existsSync(defaultData)) throw new Error('A default uninstall removed the user data.');

    // 6. Manual Setup.exe for B while A runs: A notices the activated version, restarts into it, and the
    //    unused old folder is removed.
    await run(installerOf(a), ['/S', `/D=${installed}`], { timeout: 180000 });
    results.manual = await probe(plan('manual'), async probeRoot => {
      startFrom(from);
      await waitFile(path.join(probeRoot, 'manual-ready.json'));
      await run(installerOf(b), ['/S', '--force-run', `/D=${installed}`], { timeout: 180000 });
    });
    if (results.manual.oldVersion !== 'removed' || fs.existsSync(path.join(installed, `app-${from}`))) throw new Error('The unused old version was not removed after a manual update.');

    // 7. Uninstall with "delete my data": NexusAI's data and Home folders go; other files in Home stay.
    const home = path.join(ciRoot, 'Home');
    for (const name of ['system', 'memory']) fs.mkdirSync(path.join(home, name), { recursive: true });
    fs.writeFileSync(path.join(home, 'home.json'), JSON.stringify({ format_version: 1 }));
    fs.writeFileSync(path.join(home, 'my-notes.txt'), 'not NexusAI');
    fs.writeFileSync(path.join(defaultData, 'home-pointer.json'), JSON.stringify({ path: home }));
    await uninstall(['--delete-app-data']);
    if (fs.existsSync(defaultData) || fs.existsSync(path.join(home, 'system')) || fs.existsSync(path.join(home, 'home.json')) || !fs.existsSync(path.join(home, 'my-notes.txt'))) {
      throw new Error('Deleting user data must remove exactly the NexusAI data and Home folders.');
    }

    // 8. Acceptance only: the published single-folder Beta is converted in place, where the user installed it.
    const legacyInstaller = process.env.NEXUSAI_LEGACY_INSTALLER;
    if (acceptance) {
      if (!legacyInstaller) throw new Error('Set NEXUSAI_LEGACY_INSTALLER to the published single-folder Beta installer.');
      await run(legacyInstaller, ['/S'], { timeout: 300000 });
      const registered = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', `(Get-ItemProperty -LiteralPath 'HKCU:\\Software\\${guid}').InstallLocation`], { encoding: 'utf8' });
      const legacyFolder = registered.stdout.trim();
      if (!legacyFolder || !fs.existsSync(path.join(legacyFolder, 'resources', 'app.asar'))) throw new Error(`The single-folder Beta did not install (${registered.stderr.trim()}).`);
      // The arguments the single-folder app's updater passes after its safe shutdown.
      results.legacy = await probe({ mode: 'legacy', to }, async () => {
        await run(installerOf(b), ['--updated', '/S', '--force-run'], { timeout: 300000 });
      }, legacyFolder);
      for (const expected of ['nexusai-install.ini', `app-${to}`, `${product}.exe`]) {
        if (!fs.existsSync(path.join(legacyFolder, expected))) throw new Error(`The converted installation in ${legacyFolder} lacks ${expected}.`);
      }
      if (fs.existsSync(path.join(legacyFolder, 'resources'))) throw new Error('Old single-folder files remain after conversion.');
    }

    const report = { schemaVersion: 2, sourceCommit: manifest.sourceCommit, appId, automatic: results.automatic, manual: results.manual,
      lockedOldFileUpdate: true, downgradeBlocked: true, launcherRecovery: true, orphanServiceBlocked: true, uninstallKeepsData: true,
      uninstallDeletesOnlyNexusData: true, legacyConverted: Boolean(results.legacy) };
    fs.writeFileSync(path.join(work, 'acceptance.json'), JSON.stringify(report, null, 2));
    console.log('Side-by-side install, automatic/manual updates, locked old files, downgrade, launcher recovery, process safety, uninstall'
      + (results.legacy ? ' and single-folder conversion' : '') + ' passed.');
    if (betaVersion) {
      config.ciProbe = false;
      config.acceptanceProbe = false;
      config.updateBaseUrl = '';
      config.version = betaVersion;
      await build(config);
      await test(config);
      console.log('Separate distributable Beta built without the acceptance feed.');
    }
  } finally {
    if (lock && isAlive(lock)) lock.kill();
    fs.rmSync(flag, { force: true });
    if (previous) fs.writeFileSync(configFile, previous); else fs.rmSync(configFile, { force: true });
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
};
