const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { spawn } = require('node:child_process');
const { randomUUID } = require('node:crypto');
const lib = require('./release-lib.cjs');

module.exports = async function ci({ work, configFile, build, test, run }) {
  const previous = fs.existsSync(configFile) ? fs.readFileSync(configFile) : null;
  const config = structuredClone(require('./release.example.json'));
  const ciRoot = path.join(work, 'ci');
  const feedRoot = path.join(ciRoot, 'feed');
  const probeRoot = path.join(ciRoot, 'probe');
  const defaultData = path.join(process.env.APPDATA, 'NexusAI CI');
  const flag = path.join(defaultData, 'update-probe.json');
  if (fs.existsSync(flag)) throw new Error('An earlier update probe is still registered. Remove its test app/flag before starting a fresh CI run.');
  fs.mkdirSync(probeRoot, { recursive: true });
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
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  config.updateBaseUrl = `http://127.0.0.1:${server.address().port}/windows/x64/`;
  config.ciProbe = true;
  config.companyEnvFile = '';
  config.embedCredentials = false;
  config.version = '0.0.1';
  try {
    console.log('CI uses a generic unsigned test app, synthetic local data and a loopback-only update feed.');
    await build(config);
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
    fs.writeFileSync(path.join(probeRoot, 'plan.json'), JSON.stringify({ from: '0.0.1', to: '0.0.2', nonce: randomUUID() }));
    fs.mkdirSync(defaultData, { recursive: true });
    fs.writeFileSync(flag, JSON.stringify({ directory: probeRoot }));
    const executable = path.join(process.env.LOCALAPPDATA, 'NexusAI-Pipeline-CI', 'NexusAI CI.exe');
    const app = spawn(executable, [], { stdio: 'inherit' });
    app.on('error', (error) => console.error(error));
    const deadline = Date.now() + 360000;
    const resultFile = path.join(probeRoot, 'result.json');
    while (!fs.existsSync(resultFile) && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 1000));
    if (!fs.existsSync(resultFile)) throw new Error(`Installed A did not update and relaunch as B. Inspect ${probeRoot}/app-data/desktop.log`);
    const result = JSON.parse(fs.readFileSync(resultFile, 'utf8'));
    if (!result.ok || result.to !== '0.0.2') throw new Error(`Installed update test failed: ${JSON.stringify(result)}`);
    console.log('Installed A → B update passed, including database settings, browser storage and app-data persistence.');
  } finally {
    fs.rmSync(flag, { force: true });
    if (previous) fs.writeFileSync(configFile, previous); else fs.rmSync(configFile, { force: true });
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
};
