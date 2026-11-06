const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const vm = require('node:vm');
const path = require('node:path');
const os = require('node:os');
const { EventEmitter } = require('node:events');
const { createHash } = require('node:crypto');
const runtime = require('../runtime.cjs');
const layout = require('../layout.cjs');
const source = fs.readFileSync(path.join(__dirname, '../main.cjs'), 'utf8');
function fixture(options = {}) {
  const seen = { installs: 0, exits: [], errors: [], notices: [], fetches: 0, relaunches: 0, screen: '', spawns: [], silentInstalls: 0 };
  const callbacks = new Map(), handlers = new Map(), updater = new EventEmitter();
  const app = { isPackaged: true, getPath: () => '/isolated', setPath() {}, setAppUserModelId() {},
    on: (event, fn) => callbacks.set(event, fn), requestSingleInstanceLock: () => true,
    whenReady: () => ({ then: () => ({ catch() {} }) }), getVersion: () => '0.1.0',
    exit: code => seen.exits.push(code), relaunch: () => seen.relaunches++, };
  const electron = { app, BrowserWindow: function () {}, Menu: { buildFromTemplate: () => ({ getMenuItemById: () => ({}) }), setApplicationMenu() {} },
    dialog: { showErrorBox: (...args) => seen.errors.push(args), showMessageBox: async (...args) => { seen.notices.push(args); return { response: 0 }; } },
    shell: { openPath: async () => '' }, ipcMain: { handle: (name, fn) => handlers.set(name, fn) }, Notification: {} };
  const fakeFs = { mkdirSync() {}, existsSync: () => false, appendFileSync() {}, writeFileSync() {}, readFileSync() { throw new Error('absent'); } };
  const window = { url: 'http://front/today', isDestroyed: () => false, show() {}, focus() {}, removeMenu() {}, setProgressBar() {},
    async loadFile(file) { window.url = require('node:url').pathToFileURL(file).href; window.webContents.mainFrame.url = window.url; },
    webContents: { mainFrame: { url: 'http://front/today' }, getURL: () => window.url, executeJavaScript: async script => { seen.screen = script; } } };
  // Side-by-side installations: the launcher relaunches; a silent installer adds the downloaded version.
  const spawnFake = (command, args) => {
    seen.spawns.push([command, ...args]);
    const child = new EventEmitter(); child.unref = () => {};
    queueMicrotask(() => options.relaunchError ? child.emit('error', new Error('Launcher start denied')) : child.emit('spawn'));
    return child;
  };
  const fakeLayout = { ...layout, installRoot: () => options.sideBySide ? '/install' : null, pendingVersion: () => seen.pending || null };
  const context = vm.createContext({
    require: id => id === 'electron' ? electron : id === 'electron-updater' ? { autoUpdater: updater } : id === 'node:fs' ? fakeFs
      : id === 'node:child_process' ? { spawn: spawnFake } : id === './layout.cjs' ? fakeLayout
      : id.endsWith('runtime.json') ? { appId: 'com.nexusai.pilot', dataDirectory: 'NexusAI Pilot', signed: false, updateBaseUrl: '' }
      : id === './runtime.cjs' ? { ...runtime, waitExit: (child, _, name) => runtime.waitExit(child, 20, name), waitInstalledServices: async () => { if (options.orphan) throw new Error('Owned Python is still running'); }, launchInstaller: async () => { seen.installs++; if (options.installError) throw new Error('Installer launch denied'); },
        runInstaller: async () => { seen.silentInstalls++; if (options.installCode === 0 || options.installCode === undefined) seen.pending = options.activates === false ? null : '0.2.0'; return options.installCode ?? 0; } } : require(id),
    __dirname: path.resolve(__dirname, '..'), process: { ...process, platform: 'win32', resourcesPath: '/resources', execPath: '/install/app-0.1.0/NexusAI Beta.exe', pid: 4242, argv: [] },
    fetch: async () => { seen.fetches++; return { status: options.status || 200, ok: !options.status || options.status === 200 }; },
    setTimeout, clearTimeout, setInterval, console, AbortSignal });
  vm.runInContext(source + '\n globalThis.audit = { shutdown, setupUpdates, noticeLocalUpdate, updater: autoUpdater, status: () => updateState, attach: (b,f,w) => { backend=b;frontend=f;window=w;backendUrl="http://backend";origin="http://front";startupComplete=true; }, state: () => ({ shuttingDown, canQuit, installing, lifecycleMode }) };', context);
  function service(mode) {
    const child = new EventEmitter(); child.exitCode = null; child.signalCode = null;
    child.finish = () => { child.exitCode = 0; child.emit('exit', 0, null); };
    child.stdin = { writableEnded: false, end() { this.writableEnded = true; queueMicrotask(() => {
      if (mode === 'hang') return;
      if (mode === 'signal') { child.signalCode = 'SIGTERM'; child.emit('exit', null, 'SIGTERM'); }
      else { child.exitCode = mode === 'nonzero' ? 1 : 0; child.emit('exit', child.exitCode, null); }
    }); } }; return child;
  }
  const backend = service(options.backend), frontend = service(options.frontend);
  context.audit.attach(backend, frontend, window); context.audit.setupUpdates();
  const act = action => handlers.get('nexus:action')({ sender: window.webContents, senderFrame: window.webContents.mainFrame }, action);
  const settle = () => new Promise(resolve => setImmediate(resolve));
  return { ...context.audit, seen, options, backend, frontend, act, callbacks, handlers, window, updater, settle };
}
test('busy work keeps UI/services available and postpones installation', async () => {
  const f = fixture({ status: 409 }); await f.shutdown(true);
  assert.equal(f.seen.installs, 0); assert.equal(f.backend.stdin.writableEnded, false); assert.equal(f.state().lifecycleMode, false); assert.equal(f.seen.notices.length, 1);
});
test('clean shutdown starts installer before quitting Electron', async () => {
  const f = fixture(); await f.shutdown(true); assert.equal(f.seen.installs, 1); assert.deepEqual(f.seen.exits, [0]);
});
for (const options of [{ backend: 'signal' }, { backend: 'nonzero' }, { frontend: 'nonzero' }]) test(`abnormal exit blocks install: ${JSON.stringify(options)}`, async () => {
  const f = fixture(options); await f.shutdown(true);
  assert.equal(f.seen.installs, 0); assert.equal(f.state().lifecycleMode, true); assert.equal(f.state().shuttingDown, false); assert.equal(f.seen.exits.length, 0); assert.match(f.seen.screen, /No update was installed/);
});
test('timeout has recovery and a retry never contacts the draining API again', async () => {
  const f = fixture({ backend: 'hang' }); await f.shutdown(true);
  assert.equal(f.state().lifecycleMode, true); assert.match(f.seen.screen, /still stopping/); await assert.rejects(f.act('restart'), /still stopping/);
  f.backend.finish(); await f.shutdown(true); assert.equal(f.seen.fetches, 1); assert.equal(f.seen.installs, 1); assert.deepEqual(f.seen.exits, [0]);
});
test('installer spawn failure remains visible, resets flags and permits retry', async () => {
  const f = fixture({ installError: true }); await f.shutdown(true);
  assert.equal(f.state().installing, false); assert.equal(f.state().canQuit, false); assert.match(f.seen.screen, /Installer launch denied/); assert.equal(f.seen.exits.length, 0);
  f.options.installError = false; await f.shutdown(true); assert.equal(f.seen.installs, 2); assert.deepEqual(f.seen.exits, [0]);
});
test('failed prepare-exit retains the working UI and services', async () => {
  const f = fixture({ status: 500 }); await f.shutdown(true); assert.equal(f.state().lifecycleMode, false); assert.equal(f.backend.stdin.writableEnded, false); assert.equal(f.seen.errors.length, 1);
});
test('recovery can reopen after abnormal exit and rejects foreign senders', async () => {
  const f = fixture({ backend: 'nonzero' }); await f.shutdown(true);
  await assert.rejects(f.handlers.get('nexus:action')({ sender: {}, senderFrame: {} }, 'restart'), /Untrusted/);
  await f.act('restart'); assert.equal(f.seen.relaunches, 1); assert.deepEqual(f.seen.exits, [0]);
});
test('manual installer request shares the active-work exit guard', async () => {
  const f = fixture({ status: 409 }); f.callbacks.get('second-instance')({}, ['app.exe', '--prepare-install']); await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.seen.notices.length, 1); assert.equal(f.backend.stdin.writableEnded, false);
});
test('an orphan service blocks installer launch after the parent backend exited', async () => {
  const f = fixture({ orphan: true }); await f.shutdown(true);
  assert.equal(f.backend.exitCode, 0); assert.equal(f.seen.installs, 0); assert.equal(f.seen.exits.length, 0);
  assert.match(f.seen.screen, /Owned Python is still running/);
});
test('installer handoff verifies bytes, awaits spawn, and surfaces launch errors', async () => {
  const dir = await fsp.mkdtemp(path.join(os.tmpdir(), 'nexusai-installer-')), file = path.join(dir, 'Setup.exe');
  try {
    await fsp.writeFile(file, 'verified bytes'); const update = { file, sha512: createHash('sha512').update('verified bytes').digest('base64') }; let spawned = 0;
    await runtime.launchInstaller(update, (_, args) => {
      spawned++; assert.deepEqual(args, ['--updated', '/S', '--force-run']); const child = new EventEmitter(); child.unref = () => {}; queueMicrotask(() => child.emit('spawn')); return child;
    });
    await assert.rejects(runtime.launchInstaller(update, () => { const child = new EventEmitter(); queueMicrotask(() => child.emit('error', new Error('denied'))); return child; }), /denied/);
    await fsp.writeFile(file, 'changed'); await assert.rejects(runtime.launchInstaller(update, () => { spawned++; }), /changed/); assert.equal(spawned, 1);
  } finally { await fsp.rm(dir, { recursive: true, force: true }); }
});
test('bundled-service checker waits for success and reports failure or spawn errors', async () => {
  function checker(code, message, spawnError) {
    return (exe, args) => {
      assert.match(exe, /powershell\.exe$/);
      assert.equal(args.at(-1), 'services');
      const child = new EventEmitter(); child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
      queueMicrotask(() => {
        if (spawnError) child.emit('error', new Error('PowerShell unavailable'));
        else { child.stdout.emit('data', message); child.emit('exit', code); }
      }); return child;
    };
  }
  await runtime.waitInstalledServices('/app/resources', '/app/NexusAI.exe', checker(0, 'Stopped'));
  await assert.rejects(runtime.waitInstalledServices('/app/resources', '/app/NexusAI.exe', checker(10, 'Python is still running')), /Python is still running/);
  await assert.rejects(runtime.waitInstalledServices('/app/resources', '/app/NexusAI.exe', checker(null, '', true)), /PowerShell unavailable/);
});
test('recovery actions cannot race a shutdown that is still running', async () => {
  const f = fixture({ backend: 'hang' });
  const stopping = f.shutdown(true);
  await new Promise(resolve => setImmediate(resolve));
  await assert.rejects(f.act('restart'), /still in progress/);
  const event = { prevented: false, preventDefault() { this.prevented = true; } };
  f.callbacks.get('before-quit')(event);
  assert.equal(event.prevented, true); assert.equal(f.seen.relaunches, 0);
  await stopping;
});

const downloaded = { downloadedFile: '/cache/Setup.exe', version: '0.2.0', files: [{ url: 'Setup.exe', sha512: 'x' }] };
test('side by side: a downloaded update is installed beside the running app, then a restart starts it', async () => {
  const f = fixture({ sideBySide: true });
  f.updater.emit('update-downloaded', downloaded); await f.settle(); await f.settle();
  assert.equal(f.seen.silentInstalls, 1); assert.equal(f.status().state, 'ready'); assert.equal(f.status().availableVersion, '0.2.0');
  assert.equal(f.backend.stdin.writableEnded, false, 'installing never stops the running app');
  f.updater.emit('update-available', { version: '0.2.0' });
  assert.equal(f.status().state, 'ready', 'a later check must not replace ready');
  await f.shutdown(true);
  assert.equal(f.seen.installs, 0, 'no installer at restart');
  assert.deepEqual(f.seen.spawns.at(-1), [path.join('/install', 'NexusAI Beta.exe'), '--wait-pid=4242']);
  assert.deepEqual(f.seen.exits, [0]);
});
for (const [options, pattern] of [[{ installCode: 22 }, /not enough free disk space.*NX-22/], [{ installCode: 0, activates: false }, /did not activate.*NX-34/]]) {
  test(`side by side: a failed installation is reported and the app keeps running: ${JSON.stringify(options)}`, async () => {
    const f = fixture({ sideBySide: true, ...options });
    f.updater.emit('update-downloaded', downloaded); await f.settle(); await f.settle();
    assert.equal(f.status().state, 'error'); assert.match(f.status().error, pattern);
    assert.equal(f.backend.stdin.writableEnded, false); assert.equal(f.seen.exits.length, 0);
  });
}
test('side by side: a version added by a manual Setup.exe offers a restart', async () => {
  const f = fixture({ sideBySide: true }); f.seen.pending = '0.3.0'; f.noticeLocalUpdate();
  assert.equal(f.status().state, 'ready'); assert.equal(f.status().availableVersion, '0.3.0');
});
test('side by side: a launcher that cannot start keeps the recovery screen', async () => {
  const f = fixture({ sideBySide: true, relaunchError: true }); f.seen.pending = '0.2.0'; f.noticeLocalUpdate();
  await f.shutdown(true);
  assert.match(f.seen.screen, /Launcher start denied/); assert.equal(f.seen.exits.length, 0); assert.equal(f.state().installing, false);
});
