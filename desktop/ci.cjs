const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { spawn } = require('node:child_process');
const { randomUUID } = require('node:crypto');
const { once } = require('node:events');
const lib = require('./release-lib.cjs');
const { isAlive, waitExit } = require('./runtime.cjs');

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
  const executable = path.join(installed, `${product}.exe`);
  const check = path.join(__dirname, 'installer/check-install.ps1');
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
  config.version = '0.0.1';
  const installerOf = directory => {
    const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'release.json'), 'utf8'));
    return path.join(directory, manifest.files.find(file => file.name.endsWith('.exe')).name);
  };
  const exitCode = (command, args) => new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: 'inherit', windowsHide: true });
    child.once('error', reject); child.once('exit', code => resolve(code));
  });
  const safetyArgs = ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', check, '-InstallDirectory', installed, '-AppGuid', guid, '-Version', '0.0.2', '-Mode', 'uninstall'];
  const waitFile = async file => {
    const deadline = Date.now() + 360000;
    while (!fs.existsSync(file) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 500));
    if (!fs.existsSync(file)) throw new Error(`Installed upgrade did not complete. Inspect ${file} and desktop.log.`);
  };
  const launchProbe = () => { const child = spawn(executable, [], { stdio: 'inherit' }); child.on('error', error => console.error(error)); return child; };
  try {
    console.log(`Testing ${product}: installed automatic and manual upgrades with synthetic data and a loopback feed.`);
    const a = await build(config);
    await test(config, true);
    config.version = '0.0.2';
    const b = await build(config);
    await test(config);
    const manifest = JSON.parse(fs.readFileSync(path.join(b, 'release.json'), 'utf8'));
    const feed = path.join(feedRoot, 'windows/x64/unsigned');
    const immutable = path.join(feed, manifest.version);
    fs.mkdirSync(immutable, { recursive: true });
    for (const file of manifest.files) fs.copyFileSync(path.join(b, file.name), path.join(immutable, file.name));
    fs.writeFileSync(path.join(feed, 'pilot.yml'), lib.makeChannelMetadata(fs.readFileSync(path.join(b, 'latest.yml'), 'utf8'), manifest.version, manifest.files));
    const results = {};
    for (const mode of ['automatic', 'manual']) {
      const probeRoot = path.join(ciRoot, mode);
      fs.mkdirSync(probeRoot, { recursive: true });
      fs.writeFileSync(path.join(probeRoot, 'plan.json'), JSON.stringify({ mode, from: '0.0.1', to: '0.0.2', nonce: randomUUID() }));
      fs.mkdirSync(defaultData, { recursive: true });
      fs.writeFileSync(flag, JSON.stringify({ directory: probeRoot }));
      const oldApp = launchProbe();
      if (mode === 'manual') {
        await waitFile(path.join(probeRoot, 'manual-ready.json'));
        // No --updated flag: exercise manual replacement while A is still running.
        await run(installerOf(b), ['/S', '--force-run', `/D=${installed}`], { timeout: 180000 });
      }
      const resultFile = path.join(probeRoot, 'result.json');
      await waitFile(resultFile);
      const result = JSON.parse(fs.readFileSync(resultFile, 'utf8'));
      if (!result.ok || result.to !== '0.0.2') throw new Error(`${mode} upgrade failed: ${JSON.stringify(result)}`);
      await waitExit(oldApp, 120000, 'Old installed app');
      await run('powershell.exe', safetyArgs);
      results[mode] = result;
      if (mode === 'automatic') {
        if (await exitCode(installerOf(a), ['/S', `/D=${installed}`]) === 0) throw new Error('The installer allowed a manual downgrade.');
        await run(path.join(installed, `Uninstall ${product}.exe`), ['/S', '/KEEP_APP_DATA'], { timeout: 180000 });
        await run(installerOf(a), ['/S', `/D=${installed}`], { timeout: 180000 });
      }
    }
    // An orphan owned Python must block replacement; an unrelated process must be left alone.
    const orphan = spawn(path.join(installed, 'resources/python/python.exe'), ['-c', 'import time; time.sleep(300)'], { stdio: 'ignore' });
    const unrelated = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' });
    try {
      await Promise.all([once(orphan, 'spawn'), once(unrelated, 'spawn')]);
      const code = await exitCode('powershell.exe', [...safetyArgs, '-TimeoutSeconds', '1']);
      if (code !== 10 || !isAlive(orphan) || !isAlive(unrelated)) throw new Error('Orphan/unrelated-process safety check failed.');
    } finally {
      // These two fixture PIDs were created by this test, not discovered by image name.
      if (isAlive(orphan)) orphan.kill();
      if (isAlive(unrelated)) unrelated.kill();
      await Promise.allSettled([waitExit(orphan, 10000), waitExit(unrelated, 10000)]);
    }
    const report = { schemaVersion: 1, sourceCommit: manifest.sourceCommit, appId, automatic: results.automatic, manual: results.manual, downgradeBlocked: true, orphanServiceBlocked: true };
    fs.writeFileSync(path.join(work, 'acceptance.json'), JSON.stringify(report, null, 2));
    console.log('Installed automatic/manual upgrades, data preservation, downgrade rejection and process safety passed.');
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
    fs.rmSync(flag, { force: true });
    if (previous) fs.writeFileSync(configFile, previous); else fs.rmSync(configFile, { force: true });
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
};
