const { app, BrowserWindow, Menu, dialog, shell, ipcMain, Notification } = require('electron');
const { autoUpdater } = require('electron-updater');
const { spawn } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { freePort, persistentFrontendPort, waitReady, waitExit, isAlive, launchInstaller, runInstaller, waitInstalledServices } = require('./runtime.cjs');
const layout = require('./layout.cjs');

const resources = app.isPackaged ? process.resourcesPath : path.join(__dirname, 'resources');
const config = require(path.join(resources, 'runtime.json'));
const exeName = path.basename(process.execPath);
// <install folder>\app-<version>\<exe>; the launcher one level up starts the active version.
const installHome = process.platform === 'win32' && app.isPackaged ? layout.installRoot(process.execPath) : null;
const smokeAt = process.argv.indexOf('--smoke-dir');
const smokeDir = smokeAt >= 0 ? process.argv[smokeAt + 1] : null;
if (smokeAt >= 0 && !smokeDir) throw new Error('--smoke-dir needs a directory');
const normalDataDir = path.join(app.getPath('appData'), config.dataDirectory);
let probeDir = null;
if ((config.ciProbe || config.acceptanceProbe) && !smokeDir) {
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
let updateReady = false, installing = false, menu, restartRequested = false;
let exitPrepared = false, lifecycleMode = false, shutdownRequest = false, downloadedUpdate = null;
const shutdownPage = path.join(__dirname, 'shutdown.html');
let updateState = { state: 'idle', version: app.getVersion(), availableVersion: null, percent: 0, error: null, configured: Boolean(config.updateBaseUrl) };
const startedAt = Date.now();
async function startupStage(detail) {
  log(`Startup +${Date.now() - startedAt}ms: ${detail}`);
  if (window && !window.isDestroyed()) await window.webContents.executeJavaScript(`document.getElementById('startup-detail')?.replaceChildren(${JSON.stringify(detail)})`).catch(() => {});
}
function trustedSender(event) {
  return window && event.sender === window.webContents && event.senderFrame === window.webContents.mainFrame &&
    (event.senderFrame.url.startsWith(`${origin}/`) || (lifecycleMode && event.senderFrame.url === pathToFileURL(shutdownPage).href));
}
ipcMain.handle('nexus:caption', (event, colors) => {
  if (!trustedSender(event) || process.platform !== 'win32') return;
  const valid = value => typeof value === 'string' && value.length < 64 && /^(rgba?\([\d.,\s%]+\)|#[a-fA-F\d]{6,8})$/.test(value);
  if (!valid(colors?.color) || !valid(colors?.symbolColor)) throw new Error('Invalid caption colors');
  window.setTitleBarOverlay({ color: colors.color, symbolColor: colors.symbolColor, height: 44 });
});
ipcMain.handle('nexus:status' , (event) => { if (!trustedSender(event)) throw new Error('Untrusted window'); noticeLocalUpdate(); return updateState; });
ipcMain.handle('nexus:action', async (event, action) => {
  if (!trustedSender(event)) throw new Error('Untrusted window');
  if (lifecycleMode && !['retry-shutdown', 'restart', 'quit', 'logs'].includes(action)) throw new Error('Finish shutdown before continuing.');
  if (lifecycleMode && shuttingDown && action !== 'logs') throw new Error('Shutdown is still in progress.');
  if (action === 'retry-shutdown') { void shutdown(shutdownRequest); return updateState; }
  if (action === 'restart' && lifecycleMode) {
    if (isAlive(backend) || isAlive(frontend)) throw new Error('Local services are still stopping. Retry shutdown first.');
    if (process.platform === 'win32' && app.isPackaged) await waitInstalledServices(resources, app.getPath('exe'));
    await relaunch(); canQuit = true; app.exit(0); return updateState;
  }
  if (action === 'check') {
    if (!config.updateBaseUrl || updateReady || installingBeside) return updateState;
    updateState = { ...updateState, state: 'checking', error: null };
    try { await autoUpdater.checkForUpdates(); } catch (error) { updateState = { ...updateState, state: 'error', error: error.message }; }
  } else if (action === 'download') {
    if (updateState.state === 'available') { updateState = { ...updateState, state: 'downloading' }; await autoUpdater.downloadUpdate(); }
  } else if (action === 'install') { if (updateReady) void shutdown(true); }
  else if (action === 'restart') { restartRequested = true; void shutdown(); }
  else if (action === 'quit') void shutdown();
  else if (action === 'logs') void shell.openPath(dataDir);
  else throw new Error('Unknown app action');
  return updateState;
});
ipcMain.handle('nexus:notify', (event, notice) => {
  if (!trustedSender(event) || !notice || typeof notice.title !== 'string') throw new Error('Invalid notice');
  if (!Notification.isSupported()) return false;
  const alert = new Notification({ title: notice.title.slice(0, 200), body: String(notice.body || '').slice(0, 1000), silent: notice.silent !== false });
  alert.on('click', () => { window?.show(); window?.focus(); if (typeof notice.link === 'string' && /^\/(?!\/)/.test(notice.link)) void window.loadURL(origin + notice.link); });
  alert.show(); return true;
});
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
    if (lifecycleMode && !shuttingDown) {
      void lifecycleScreen('Local services have stopped. Retry shutdown to continue, or reopen NexusAI.', true);
      return;
    }
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

async function lifecycleScreen(detail, retry = false) {
  lifecycleMode = true;
  if (!window || window.isDestroyed()) return;
  if (window.webContents.getURL() !== pathToFileURL(shutdownPage).href) await window.loadFile(shutdownPage);
  window.show();
  await window.webContents.executeJavaScript(`document.getElementById('detail').textContent=${JSON.stringify(detail)};document.getElementById('retry').disabled=${!retry};document.getElementById('restart').disabled=${!retry || isAlive(backend) || isAlive(frontend)};`).catch(() => {});
}

async function shutdown(update = false, failedStartup = false) {
  if (shuttingDown) return;
  shuttingDown = true;
  shutdownRequest = update;
  try {
    if (!exitPrepared && isAlive(backend) && backendUrl && startupComplete && !failedStartup) {
      const response = await fetch(`${backendUrl}/__desktop__/prepare-exit`, {
        method: 'POST', headers: { 'x-nexusai-desktop': controlToken }, signal: AbortSignal.timeout(10000),
      });
      if (response.status === 409) {
        shuttingDown = false;
        restartRequested = false;
        if (probeDir) {
          if (++probeExitAttempts > 60) throw new Error('CI app did not become idle for its update.');
          setTimeout(() => void shutdown(update), 1000);
          return;
        }
        await showMessage('NexusAI is still working. Finish or pause the active chat/import and try again. The update will wait.');
        return;
      }
      if (!response.ok) throw new Error(`Could not prepare a safe exit (${response.status}).`);
      exitPrepared = true;
    }
    await lifecycleScreen('Waiting for local services to finish. No update has been installed.');
    // Closing browser/SSE connections allows Uvicorn to drain. Never terminate Python forcibly.
    if (isAlive(frontend) && !frontend.stdin.writableEnded) frontend.stdin.end();
    if (isAlive(backend) && !backend.stdin.writableEnded) backend.stdin.end();
    const stopped = await Promise.allSettled([waitExit(frontend, 120000, 'Interface'), waitExit(backend, 120000, 'Python backend')]);
    if (!failedStartup) {
      for (let i = 0; i < stopped.length; i++) {
        const result = stopped[i];
        if (result.status === 'rejected') throw result.reason;
        if ([frontend, backend][i] && result.value !== 0) throw new Error(`${i ? 'Python backend' : 'Interface'} did not exit cleanly (${result.value}). No update was installed.`);
      }
    } else if (isAlive(backend) || isAlive(frontend)) throw new Error('A local service is still stopping. Retry shutdown.');
    if (smokeDir) {
      fs.writeFileSync(path.join(smokeDir, 'result.json'), JSON.stringify({
        ok: !failedStartup && errors.length === 0, version: app.getVersion(), errors,
      }, null, 2));
    }
    if (probeDir && probeReport) fs.writeFileSync(path.join(probeDir, 'result.json'), JSON.stringify(probeReport, null, 2));
    if (update) {
      installing = true;
      await lifecycleScreen('Checking that all bundled local services have stopped…');
      if (process.platform === 'win32' && app.isPackaged) await waitInstalledServices(resources, app.getPath('exe'));
      if (installHome) {
        // The new version is already installed beside this one; restarting is all that is left.
        await lifecycleScreen('Starting the updated NexusAI…');
        await relaunch();
      } else {
        await lifecycleScreen('Starting the verified update installer…');
        await launchInstaller(downloadedUpdate);
      }
      canQuit = true; app.exit(0);
    } else { canQuit = true; if (restartRequested && !failedStartup) await relaunch(); app.exit(failedStartup || errors.length ? 1 : 0); }
  } catch (error) {
    log(error.stack);
    shuttingDown = false;
    installing = false;
    restartRequested = false;
    updateState = { ...updateState, state: updateReady ? 'ready' : 'error', error: error.message };
    if (probeDir) {
      fs.writeFileSync(path.join(probeDir, 'result.json'), JSON.stringify({ ok: false, error: error.message }));
      canQuit = true; app.exit(1); return;
    }
    // A partly stopped app must be relaunched before further work; no binary replacement occurs.
    if (lifecycleMode) await lifecycleScreen(`${error.message}\n\nNo update was installed. Logs: ${logPath}`, true);
    else dialog.showErrorBox('NexusAI could not close safely', `${error.message}\n\nNo update was installed. Logs: ${logPath}`);
    if (smokeDir && !isAlive(backend) && !isAlive(frontend)) { canQuit = true; app.exit(1); }
  }
}

function updateItem(label) {
  const item = menu?.getMenuItemById('update-status');
  if (item) item.label = label;
}

function setupUpdates() {
  autoUpdater.autoDownload = Boolean(probeDir);
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
        try { await autoUpdater.checkForUpdates(); if (!updateReady) await showMessage('Update check completed. Open Settings → About & Updates to download an available update.'); }
        catch (error) { await showMessage(`Could not check for updates: ${error.message}`); }
      } },
      { label: 'Restart to update', click: () => updateReady ? void shutdown(true) : void showMessage('No downloaded update is ready.') },
      { label: 'Receive beta updates', type: 'checkbox', checked: channel === 'pilot', enabled: config.signed,
        click: (item) => { useChannel(item.checked ? 'pilot' : 'stable'); void showMessage('Update channel saved. Check for updates to use it.'); } },
      { label: 'Open logs folder', click: () => void shell.openPath(dataDir) },
      { type: 'separator' }, { label: 'Quit', click: () => void shutdown() },
    ] },
    { role: 'editMenu' }, { role: 'viewMenu' },
  ]);
  Menu.setApplicationMenu(menu);
  if (process.platform !== 'darwin') window.removeMenu();
  // Once a version is installed beside this one, later checks must not replace "ready" with "available".
  const settled = () => updateReady || installingBeside;
  autoUpdater.on('checking-for-update', () => { if (!settled()) updateState = { ...updateState, state: 'checking', error: null }; });
  autoUpdater.on('update-available', (info) => { if (!settled()) updateState = { ...updateState, state: 'available', availableVersion: info.version }; });
  autoUpdater.on('update-not-available', () => { if (!settled()) updateState = { ...updateState, state: 'current' }; });
  autoUpdater.on('error', (error) => {
    if (settled()) { log(`Update check error after installation: ${error.message}`); return; }
    updateState = { ...updateState, state: 'error', error: error.message };
    log(`Update error: ${error.message}`); window?.setProgressBar(-1); updateItem('Update failed — click to retry');
    if (probeDir) { probeReport = { ok: false, error: error.message }; void shutdown(false, true); }
  });
  autoUpdater.on('download-progress', ({ percent }) => {
    if (settled()) return;
    updateState = { ...updateState, state: 'downloading', percent };
    updateItem(`Downloading update: ${Math.round(percent)}%`);
    window?.setProgressBar(percent / 100);
  });
  autoUpdater.on('update-downloaded', (info) => {
    downloadedUpdate = { file: info.downloadedFile, sha512: info.files?.find(file => /\.exe(?:$|\?)/i.test(file.url))?.sha512 };
    window?.setProgressBar(-1);
    if (installHome) void installBeside(info.version);
    else markReady(info.version);
  });
  if (installHome && !smokeDir) {
    // Old version folders go once nothing holds their files; a locked folder only waits for the next pass.
    setTimeout(() => void cleanUpInstallation(), probeDir ? 1000 : 60000).unref();
    setInterval(() => void cleanUpInstallation(), 15 * 60 * 1000).unref();
    setInterval(noticeLocalUpdate, probeDir ? 2000 : 60000).unref();
  }
  if (config.updateBaseUrl && !smokeDir && !probeDir) {
    setTimeout(() => { if (!updateReady) void autoUpdater.checkForUpdates().catch(() => {}); }, 15000).unref();
    setInterval(() => { if (!updateReady) void autoUpdater.checkForUpdates().catch(() => {}); }, 4 * 60 * 60 * 1000).unref();
  }
}

// Starts the active version once this process has exited, through the launcher in the installation folder.
function relaunch() {
  if (!installHome) { app.relaunch(); return Promise.resolve(); }
  return new Promise((resolve, reject) => {
    const starter = spawn(path.join(installHome, exeName), [`--wait-pid=${process.pid}`], { detached: true, stdio: 'ignore', windowsHide: true });
    starter.once('error', reject);
    starter.once('spawn', () => { starter.unref(); resolve(); });
  });
}

function markReady(version) {
  if (updateReady) return;
  updateState = { ...updateState, state: 'ready', availableVersion: version || updateState.availableVersion, percent: 100, error: null };
  updateReady = true; updateItem('Restart to update'); window?.setProgressBar(-1);
  log(`Update ${version} is ready; it starts on the next restart.`);
  if (probeDir) { void shutdown(true); return; }
  void dialog.showMessageBox(window, { message: 'A NexusAI update is ready.', detail: 'Restart when your current work is finished.',
    buttons: ['Later', 'Restart to update'], defaultId: 0, cancelId: 0,
  }).then(({ response }) => { if (response === 1) void shutdown(true); });
}

// The installer adds the new version beside this one while NexusAI keeps running; nothing in use is touched.
let installingBeside = false;
async function installBeside(version) {
  if (installingBeside || updateReady) return;
  installingBeside = true;
  updateState = { ...updateState, state: 'installing', percent: 100, error: null };
  updateItem('Installing update…');
  try {
    const code = await runInstaller(downloadedUpdate);
    log(`Update installer for ${version} exited with ${code}.`);
    const pending = layout.pendingVersion(installHome, app.getVersion(), exeName);
    if (code === 0 && pending) markReady(pending);
    else throw new Error(code === 0 ? 'The installer finished but did not activate the new version. (Error NX-34)' : layout.installerError(code));
  } catch (error) {
    log(`Update installation failed: ${error.message}`);
    updateState = { ...updateState, state: 'error', error: error.message };
    updateItem('Update failed — click to retry');
    if (probeDir) { probeReport = { ok: false, error: error.message }; void shutdown(false, true); }
  } finally { installingBeside = false; }
}

// A Setup.exe run by hand while NexusAI is open adds and activates a newer version the same way.
function noticeLocalUpdate() {
  if (!installHome || updateReady || installingBeside) return;
  const pending = layout.pendingVersion(installHome, app.getVersion(), exeName);
  if (pending) markReady(pending);
}

let housekeeping = null;
function cleanUpInstallation() {
  if (housekeeping) return housekeeping;
  if (!installHome || shuttingDown) return Promise.resolve({});
  housekeeping = layout.cleanup(installHome, app.getVersion(), log)
    .catch(error => { log(`Cleanup error: ${error.stack || error.message}`); return {}; })
    .finally(() => { housekeeping = null; });
  return housekeeping;
}

async function cleanUpUntil(done, timeout) {
  const deadline = Date.now() + timeout;
  for (;;) {
    await cleanUpInstallation();
    if (done() || Date.now() >= deadline) return done();
    await new Promise(resolve => setTimeout(resolve, 2000));
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
    if (plan.mode === 'manual') fs.writeFileSync(path.join(probeDir, 'manual-ready.json'), JSON.stringify({ version: app.getVersion(), nonce: plan.nonce }));
    else await autoUpdater.checkForUpdates();
  } else if (app.getVersion() === plan.to && plan.mode === 'legacy') {
    // The one-time conversion of an old single-folder installation: its leftovers go once nothing holds them.
    const removed = await cleanUpUntil(() => !fs.existsSync(path.join(installHome, '.legacy-files')), 90000);
    probeReport = { ok: removed, mode: 'legacy', to: app.getVersion(), legacyRemoved: removed, ...(removed ? {} : { error: 'Old single-folder files were not removed.' }) };
    await shutdown();
  } else if (app.getVersion() === plan.to) {
    const settings = await api('/api/queries/settings.get');
    const browserMarker = await window.webContents.executeJavaScript("localStorage.getItem('nexusai.updateProbe')");
    const status = await api('/api/home/status');
    if (settings.theme !== 'nexus-dark' || browserMarker !== plan.nonce || fs.readFileSync(marker, 'utf8') !== plan.nonce || status.state !== 'ready') {
      throw new Error('The installed update did not preserve its database/browser/app-data fixtures.');
    }
    fs.writeFileSync(path.join(probeDir, 'after.png'), (await window.capturePage()).toPNG());
    // The test may hold a file of the old version open: the update must still work, and the folder stays until it is free.
    const oldFolder = path.join(installHome, `app-${plan.from}`);
    const removed = await cleanUpUntil(() => !fs.existsSync(oldFolder), plan.oldLocked ? 0 : 60000);
    probeReport = { ok: removed !== Boolean(plan.oldLocked), mode: plan.mode || 'automatic', from: plan.from, to: app.getVersion(), settingsPreserved: true,
      browserStoragePreserved: true, appDataPreserved: true, homeReady: true, oldVersion: removed ? 'removed' : 'kept' };
    await shutdown();
  } else throw new Error(`Unexpected installed version in CI: ${app.getVersion()}`);
}

async function start() {
  window = new BrowserWindow({ width: 1440, height: 940, minWidth: 1000, minHeight: 700, show: true,
    ...(process.platform === 'win32' ? { titleBarStyle: 'hidden', titleBarOverlay: { color: '#f4efe6', symbolColor: '#211e1a', height: 44 } } : {}),
    icon: path.join(__dirname, 'build-resources', 'icon.png'),
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, preload: path.join(__dirname, 'preload.cjs'), autoplayPolicy: 'no-user-gesture-required' } });
  window.on('close', (event) => {
    if (!canQuit) {
      event.preventDefault();
      if (shuttingDown) return;
      if (lifecycleMode && !isAlive(backend) && !isAlive(frontend)) { canQuit = true; app.exit(0); }
      else void shutdown();
    }
  });
  if (installHome) {
    // A taskbar pin must start the launcher, never a version folder that is removed after an update.
    const launcher = path.join(installHome, exeName);
    window.setAppDetails({ appId: config.appId, appIconPath: launcher, appIconIndex: 0, relaunchCommand: `"${launcher}"`, relaunchDisplayName: path.basename(exeName, '.exe') });
  }
  await window.loadFile(path.join(__dirname, 'loading.html'));
  await startupStage('Preparing your local services…');
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
  const site = path.join(resources, 'frontend');
  frontend = child(path.join(resources, 'node', process.platform === 'win32' ? 'node.exe' : 'node'),
    [path.join(resources, 'frontend-server.cjs'), path.join(site, 'server.js')], { cwd: site, env: { ...env, PORT: String(frontendPort), HOSTNAME: '127.0.0.1',
      NEXUSAI_DESKTOP_BACKEND_URL: backendUrl } });
  await startupStage('Opening your encrypted workspace and starting the interface…');
  await Promise.all([waitReady(`${backendUrl}/api/health`, backend), waitReady(`http://127.0.0.1:${frontendPort}`, frontend)]);
  await startupStage('Connecting your workspace…');
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
  await startupStage('Workspace ready. Opening NexusAI…');
  await window.loadURL(origin);
  log(`Startup complete: ${Date.now() - startedAt}ms`);
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
  if (!canQuit) {
    if (shuttingDown) { event.preventDefault(); return; }
    if (lifecycleMode && !isAlive(backend) && !isAlive(frontend)) { canQuit = true; return; }
    event.preventDefault(); void shutdown();
  }
});
if (!app.requestSingleInstanceLock()) app.exit(0);
else if (process.argv.includes('--prepare-install')) app.exit(0);
else {
  app.on('second-instance', (_, argv) => {
    if (argv.includes('--prepare-install')) { restartRequested = false; void shutdown(); }
    else if (window) { window.show(); window.focus(); }
  });
  app.whenReady().then(start).catch(async (error) => {
    errors.push(error.message); log(error.stack);
    if (probeDir) probeReport = { ok: false, error: error.message, version: app.getVersion() };
    if (!smokeDir && !probeDir) dialog.showErrorBox('NexusAI could not start', `${error.message}\n\nLogs: ${logPath}`);
    await shutdown(false, true);
  });
}
