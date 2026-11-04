const { app, BrowserWindow, Menu, dialog, shell } = require('electron');
const { autoUpdater } = require('electron-updater');
const { spawn } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { freePort, persistentFrontendPort, waitReady, waitExit } = require('./runtime.cjs');

const resources = app.isPackaged ? process.resourcesPath : path.join(__dirname, 'resources');
const config = require(path.join(resources, 'runtime.json'));
const smokeAt = process.argv.indexOf('--smoke-dir');
const smokeDir = smokeAt >= 0 ? process.argv[smokeAt + 1] : null;
if (smokeAt >= 0 && !smokeDir) throw new Error('--smoke-dir needs a directory');
const normalDataDir = path.join(app.getPath('appData'), config.dataDirectory);
let probeDir = null;
if (config.ciProbe && !smokeDir) {
  const probeFile = path.join(normalDataDir, 'update-probe.json');
  if (fs.existsSync(probeFile)) probeDir = JSON.parse(fs.readFileSync(probeFile, 'utf8')).directory;
}
const dataDir = smokeDir ? path.resolve(smokeDir) : probeDir ? path.join(probeDir, 'app-data') : normalDataDir;
fs.mkdirSync(dataDir, { recursive: true });
app.setPath('userData', path.join(dataDir, 'browser'));
app.setAppUserModelId(config.appId);
const logPath = path.join(dataDir, 'desktop.log');
const log = (message) => fs.appendFileSync(logPath, `${new Date().toISOString()} ${message}\n`);
let window, backend, frontend, backendUrl, origin, shuttingDown = false, canQuit = false;
let updateReady = false, installing = false, menu;
let startupComplete = false;
let probeReport = null, probeExitAttempts = 0;
const controlToken = randomBytes(32).toString('hex');
const errors = [];

function child(command, args, options) {
  const service = spawn(command, args, { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], ...options });
  service.stdout.on('data', (data) => log(String(data)));
  service.stderr.on('data', (data) => log(String(data)));
  service.on('error', (error) => { service.spawnError = error; log(`Service error: ${error.message}`); });
  service.on('exit', (code, signal) => {
    log(`Service exited: ${path.basename(command)} code=${code} signal=${signal}`);
    if (!shuttingDown && window && startupComplete) {
      window.hide();
      if (!probeDir) dialog.showErrorBox('NexusAI service stopped', `A local service stopped. Restart NexusAI.\n\nLogs: ${logPath}`);
      else probeReport = { ok: false, error: 'A local service stopped during the update probe.' };
      void shutdown(false, true);
    }
  });
  return service;
}

function showMessage(message) { return dialog.showMessageBox(window, { message, type: 'info' }); }

async function shutdown(update = false, failedStartup = false) {
  if (shuttingDown) return;
  shuttingDown = true;
  try {
    if (backend && backend.exitCode === null && backendUrl && startupComplete && !failedStartup) {
      const response = await fetch(`${backendUrl}/__desktop__/prepare-exit`, {
        method: 'POST', headers: { 'x-nexusai-desktop': controlToken }, signal: AbortSignal.timeout(10000),
      });
      if (response.status === 409) {
        shuttingDown = false;
        if (probeDir) {
          if (++probeExitAttempts > 60) throw new Error('CI app did not become idle for its update.');
          setTimeout(() => void shutdown(update), 1000);
          return;
        }
        await showMessage('NexusAI is still working. Finish or pause the active chat/import and try again. The update will wait.');
        return;
      }
      if (!response.ok) throw new Error(`Could not prepare a safe exit (${response.status}).`);
    }
    window?.hide();
    // Closing browser/SSE connections allows Uvicorn to drain. Never terminate Python forcibly.
    if (frontend?.exitCode === null) frontend.stdin.end();
    backend?.stdin.end();
    await waitExit(frontend);
    const code = await waitExit(backend);
    if (!failedStartup && code !== null && code !== undefined && code !== 0) throw new Error(`Backend did not exit cleanly (${code}); update postponed.`);
    if (smokeDir) {
      fs.writeFileSync(path.join(smokeDir, 'result.json'), JSON.stringify({
        ok: !failedStartup && errors.length === 0, version: app.getVersion(), errors,
      }, null, 2));
    }
    if (probeDir && probeReport) fs.writeFileSync(path.join(probeDir, 'result.json'), JSON.stringify(probeReport, null, 2));
    canQuit = true;
    if (update) { installing = true; autoUpdater.quitAndInstall(true, true); }
    else app.exit(failedStartup || errors.length ? 1 : 0);
  } catch (error) {
    log(error.stack);
    shuttingDown = false;
    if (probeDir) {
      fs.writeFileSync(path.join(probeDir, 'result.json'), JSON.stringify({ ok: false, error: error.message }));
      canQuit = true; app.exit(1); return;
    }
    // A partly stopped app must be relaunched before further work; no binary replacement occurs.
    dialog.showErrorBox('NexusAI could not close safely', `${error.message}\n\nNo update was installed. Logs: ${logPath}`);
    if (smokeDir || (backend && backend.exitCode !== null)) { canQuit = true; app.exit(1); }
  }
}

function updateItem(label) {
  const item = menu?.getMenuItemById('update-status');
  if (item) item.label = label;
}

function setupUpdates() {
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = false;
  autoUpdater.allowDowngrade = false;
  const channelFile = path.join(dataDir, 'update-channel');
  let channel = config.signed ? 'stable' : 'pilot';
  try { channel = fs.readFileSync(channelFile, 'utf8').trim(); } catch { /* First install. */ }
  if (!['stable', 'pilot'].includes(channel) || (!config.signed && channel === 'stable')) channel = 'pilot';
  const useChannel = (value) => {
    fs.writeFileSync(channelFile, value);
    autoUpdater.channel = value === 'stable' ? 'latest' : 'pilot';
    autoUpdater.allowDowngrade = false;
  };
  useChannel(channel);
  menu = Menu.buildFromTemplate([
    { label: 'NexusAI', submenu: [
      { label: `Version ${app.getVersion()}`, enabled: false },
      { id: 'update-status', label: 'Check for updates', click: async () => {
        if (!config.updateBaseUrl) return showMessage('Updates are not configured in this local test build.');
        try { await autoUpdater.checkForUpdates(); if (!updateReady) await showMessage('Update check completed. Any available update downloads in the background.'); }
        catch (error) { await showMessage(`Could not check for updates: ${error.message}`); }
      } },
      { label: 'Restart to update', click: () => updateReady ? void shutdown(true) : void showMessage('No downloaded update is ready.') },
      { label: 'Receive pilot updates', type: 'checkbox', checked: channel === 'pilot', enabled: config.signed,
        click: (item) => { useChannel(item.checked ? 'pilot' : 'stable'); void showMessage('Update channel saved. Check for updates to use it.'); } },
      { label: 'Open logs folder', click: () => void shell.openPath(dataDir) },
      { type: 'separator' }, { label: 'Quit', click: () => void shutdown() },
    ] },
    { role: 'editMenu' }, { role: 'viewMenu' },
  ]);
  Menu.setApplicationMenu(menu);
  autoUpdater.on('error', (error) => {
    log(`Update error: ${error.message}`); window?.setProgressBar(-1); updateItem('Update failed — click to retry');
    if (probeDir) { probeReport = { ok: false, error: error.message }; void shutdown(false, true); }
  });
  autoUpdater.on('download-progress', ({ percent }) => {
    updateItem(`Downloading update: ${Math.round(percent)}%`);
    window?.setProgressBar(percent / 100);
  });
  autoUpdater.on('update-downloaded', () => {
    updateReady = true; updateItem('Update ready'); window?.setProgressBar(-1);
    if (probeDir) { void shutdown(true); return; }
    void dialog.showMessageBox(window, { message: 'A NexusAI update is ready.', detail: 'Restart when your current work is finished.',
      buttons: ['Later', 'Restart to update'], defaultId: 0, cancelId: 0,
    }).then(({ response }) => { if (response === 1) void shutdown(true); });
  });
  if (config.updateBaseUrl && !smokeDir && !probeDir) {
    setTimeout(() => void autoUpdater.checkForUpdates().catch(() => {}), 15000).unref();
    setInterval(() => void autoUpdater.checkForUpdates().catch(() => {}), 4 * 60 * 60 * 1000).unref();
  }
}

async function runUpdateProbe() {
  const plan = JSON.parse(fs.readFileSync(path.join(probeDir, 'plan.json'), 'utf8'));
  const api = async (endpoint, body = {}) => {
    const response = await fetch(`${origin}${endpoint}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    if (!response.ok) throw new Error(`CI fixture request failed: ${endpoint} (${response.status})`);
    return response.json();
  };
  const marker = path.join(dataDir, 'persistence-marker');
  if (app.getVersion() === plan.from) {
    await api('/api/commands/settings.update', { theme: 'nexus-dark' });
    fs.writeFileSync(marker, plan.nonce);
    await window.webContents.executeJavaScript(`localStorage.setItem('nexusai.updateProbe', ${JSON.stringify(plan.nonce)})`);
    window.webContents.session.flushStorageData();
    fs.writeFileSync(path.join(probeDir, 'before.png'), (await window.capturePage()).toPNG());
    autoUpdater.disableDifferentialDownload = true;
    await autoUpdater.checkForUpdates();
  } else if (app.getVersion() === plan.to) {
    const settings = await api('/api/queries/settings.get');
    const browserMarker = await window.webContents.executeJavaScript("localStorage.getItem('nexusai.updateProbe')");
    const status = await api('/api/home/status');
    if (settings.theme !== 'nexus-dark' || browserMarker !== plan.nonce || fs.readFileSync(marker, 'utf8') !== plan.nonce || status.state !== 'ready') {
      throw new Error('The installed update did not preserve its database/browser/app-data fixtures.');
    }
    fs.writeFileSync(path.join(probeDir, 'after.png'), (await window.capturePage()).toPNG());
    probeReport = { ok: true, from: plan.from, to: app.getVersion(), settingsPreserved: true, browserStoragePreserved: true, appDataPreserved: true, homeReady: true };
    await shutdown();
  } else throw new Error(`Unexpected installed version in CI: ${app.getVersion()}`);
}

async function start() {
  window = new BrowserWindow({ width: 1440, height: 940, minWidth: 1000, minHeight: 700, show: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true } });
  window.on('close', (event) => { if (!canQuit) { event.preventDefault(); void shutdown(); } });
  await window.loadFile(path.join(__dirname, 'loading.html'));
  const frontendPort = await persistentFrontendPort(dataDir);
  let backendPort = await freePort();
  while (frontendPort === backendPort) backendPort = await freePort();
  backendUrl = `http://127.0.0.1:${backendPort}`;
  origin = `http://127.0.0.1:${frontendPort}`;
  const env = { ...process.env, NEXUSAI_APP_DATA: dataDir, NEXUSAI_HOST: '127.0.0.1',
    TZ: process.env.TZ || Intl.DateTimeFormat().resolvedOptions().timeZone,
    NEXUSAI_PORT: String(backendPort), NEXUSAI_ALLOWED_ORIGINS: `${origin},${backendUrl}`,
    NEXUSAI_ENV_FILE: path.join(dataDir, 'company.env'), PYTHONUTF8: '1', PYTHONNOUSERSITE: '1',
    NEXUSAI_ENV_DEFAULTS_FILE: path.join(resources, 'deployment.env'),
  };
  if (smokeDir) { delete env.NEXUSAI_HOME; delete env.NEXUSAI_SECRETS_TEST_FILE; }
  if (probeDir) {
    env.NEXUSAI_HOME = path.join(probeDir, 'Home');
    env.NEXUSAI_LEARN_EMAILS = '0';
  }
  log(`Starting NexusAI ${app.getVersion()} (${config.signed ? 'signed' : 'unsigned pilot'})`);
  backend = child(path.join(resources, 'python', process.platform === 'win32' ? 'python.exe' : 'bin/python3'),
    ['-m', 'nexusai.api.desktop'], { env: { ...env, NEXUSAI_DESKTOP_CONTROL_TOKEN: controlToken }, cwd: dataDir });
  await waitReady(`${backendUrl}/api/health`, backend);
  const site = path.join(resources, 'frontend');
  frontend = child(path.join(resources, 'node', process.platform === 'win32' ? 'node.exe' : 'node'),
    [path.join(resources, 'frontend-server.cjs'), path.join(site, 'server.js')], { cwd: site, env: { ...env, PORT: String(frontendPort), HOSTNAME: '127.0.0.1',
      NEXUSAI_DESKTOP_BACKEND_URL: backendUrl } });
  await waitReady(`${origin}/api/health`, frontend);
  const proxyStatus = await fetch(`${origin}/api/home/status`, { method: 'POST', signal: AbortSignal.timeout(10000) });
  if (!proxyStatus.ok) throw new Error(`Frontend authentication/proxy check failed (${proxyStatus.status}).`);
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) void shell.openExternal(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    if (new URL(url).origin !== origin) { event.preventDefault(); if (/^https?:\/\//.test(url)) void shell.openExternal(url); }
  });
  window.webContents.on('render-process-gone', (_, details) => errors.push(`Renderer stopped: ${details.reason}`));
  window.webContents.on('console-message', (details) => {
    if (details.level === 'error') { log(`Renderer: ${details.message}`); if (smokeDir) errors.push(details.message); }
  });
  window.webContents.session.webRequest.onCompleted((details) => {
    if (smokeDir && details.url.startsWith(origin) && details.statusCode >= 400) errors.push(`HTTP ${details.statusCode}: ${details.url}`);
  });
  await window.loadURL(origin);
  startupComplete = true;
  window.show();
  setupUpdates();
  if (probeDir) await runUpdateProbe();
  if (smokeDir) {
    await new Promise((resolve) => setTimeout(resolve, 5000));
    const body = await window.webContents.executeJavaScript('document.body.innerText');
    if (!body || body.length < 20) errors.push('The app rendered an empty page.');
    fs.writeFileSync(path.join(smokeDir, 'window.png'), (await window.capturePage()).toPNG());
    await shutdown();
  }
}

app.on('before-quit', (event) => {
  if (!canQuit && !installing) { event.preventDefault(); void shutdown(); }
});
if (!app.requestSingleInstanceLock()) app.exit(0);
else {
  app.on('second-instance', () => { if (window) { window.show(); window.focus(); } });
  app.whenReady().then(start).catch(async (error) => {
    errors.push(error.message); log(error.stack);
    if (probeDir) probeReport = { ok: false, error: error.message, version: app.getVersion() };
    if (!smokeDir && !probeDir) dialog.showErrorBox('NexusAI could not start', `${error.message}\n\nLogs: ${logPath}`);
    await shutdown(false, true);
  });
}
