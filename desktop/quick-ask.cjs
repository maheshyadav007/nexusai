const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

// The quick-ask box: a system-wide shortcut opens a small chat at the bottom of the screen, with
// whatever text was selected in the app in front. Pure helpers first; the Electron wiring is
// createQuickAsk, which takes Electron's modules so tests can hand it fakes.

const DEFAULTS = Object.freeze({ shortcut: 'Control+Alt+Space', enabled: true, selection: true, trayNoticeShown: false });
// The box itself, and the room around it for its shadow. The page draws the box; this is the window.
const WIDTH = 760, MARGIN = 24, MIN_HEIGHT = 96, MAX_HEIGHT = 640;
const SELECTION_LIMIT = 8000;
const SHOW_AFTER = 40;
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const MODIFIERS = new Set(['Control', 'Alt', 'Shift', 'Super', 'Command']);
const KEY = /^(?:[A-Z0-9]|F(?:[1-9]|1[0-9]|2[0-4])|Space|Enter|Tab|Backspace|Delete|Insert|Home|End|PageUp|PageDown|Up|Down|Left|Right|Escape|Plus|[`\-=[\]\\;',./])$/;

/** "Control+Alt+Space" and the like: one or more modifiers, then exactly one key. */
function validShortcut(value) {
  if (typeof value !== 'string' || value.length > 64) return false;
  const parts = value.split('+');
  const key = parts.pop();
  if (!parts.length || !KEY.test(key)) return false;
  if (new Set(parts).size !== parts.length || !parts.every((part) => MODIFIERS.has(part))) return false;
  // Shift alone only changes the letter; it can't make a shortcut.
  return parts.some((part) => part !== 'Shift');
}

function readSettings(file) {
  try {
    const saved = JSON.parse(fs.readFileSync(file, 'utf8'));
    const settings = { ...DEFAULTS };
    if (validShortcut(saved.shortcut)) settings.shortcut = saved.shortcut;
    for (const flag of ['enabled', 'selection', 'trayNoticeShown']) if (typeof saved[flag] === 'boolean') settings[flag] = saved[flag];
    return settings;
  } catch { return { ...DEFAULTS }; }
}

function writeSettings(file, settings) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(settings, null, 2));
}

/** Bottom centre of the screen's usable area, so it sits above the taskbar or Dock. */
function placement(area, height = MIN_HEIGHT) {
  const width = Math.min(WIDTH, area.width);
  const tall = Math.min(Math.max(height, MIN_HEIGHT), MAX_HEIGHT, area.height);
  return { x: Math.round(area.x + (area.width - width) / 2), y: area.y + area.height - tall - MARGIN, width, height: tall };
}

/** A new height for the box, growing upward: its bottom edge stays where the person saw it. */
function grow(bounds, height, area) {
  const tall = Math.min(Math.max(Math.round(height), MIN_HEIGHT), MAX_HEIGHT, area.height);
  const bottom = bounds.y + bounds.height;
  return { ...bounds, y: Math.max(area.y, bottom - tall), height: tall };
}

/**
 * Copies the selection in the app in front and gives back its text, leaving the clipboard as it
 * was. Returns '' when nothing was selected. `copy` presses the platform's copy keys there.
 */
async function captureSelection({ clipboard, copy, wait: pause = wait, timeout = 300 }) {
  // Nothing is written to the clipboard first: with Windows clipboard history every write is kept.
  // So an unchanged clipboard means nothing was selected, or the same text as was last copied.
  const before = clipboard.readText();
  const saved = { text: before, html: clipboard.readHTML(), rtf: clipboard.readRTF(), image: clipboard.readImage() };
  let text = '';
  try {
    if (!(await copy())) return '';
    for (let waited = 0; waited <= timeout; waited += 20) {
      const now = clipboard.readText();
      if (now !== before) { text = now; break; }
      await pause(20);
    }
  } finally {
    // Only a clipboard the copy changed is written back.
    if (clipboard.readText() !== before) {
      const restore = {};
      if (saved.text) restore.text = saved.text;
      if (saved.html) restore.html = saved.html;
      if (saved.rtf) restore.rtf = saved.rtf;
      if (saved.image && !saved.image.isEmpty()) restore.image = saved.image;
      if (Object.keys(restore).length) clipboard.write(restore); else clipboard.clear();
    }
  }
  return text.trim().slice(0, SELECTION_LIMIT);
}

// macOS: waits for the person to let go of the shortcut's keys, then posts Command-C with only
// Command held, so the keys still down can't turn it into another shortcut. Needs Accessibility.
const MAC_COPY = `ObjC.import('CoreGraphics');
const held = () => $.CGEventSourceFlagsState(1) & (0x100000 | 0x80000 | 0x40000 | 0x20000);
for (let i = 0; i < 40 && held(); i++) delay(0.02);
for (const down of [true, false]) { const key = $.CGEventCreateKeyboardEvent(null, 8, down); $.CGEventSetFlags(key, 0x100000); $.CGEventPost(0, key); }`;

// Windows: one PowerShell kept running, because starting it and compiling this costs a second.
// Waits for the shortcut's keys to come up, presses Ctrl+C, and answers "done".
const WINDOWS_COPY = `$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices; using System.Threading;
public static class NexusKeys {
  [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);
  [DllImport("user32.dll")] static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
  static bool Held() { foreach (int key in new[] { 0x10, 0x11, 0x12, 0x5B, 0x5C }) if ((GetAsyncKeyState(key) & 0x8000) != 0) return true; return false; }
  public static void Copy() {
    for (int i = 0; i < 40 && Held(); i++) Thread.Sleep(20);
    keybd_event(0x11, 0, 0, UIntPtr.Zero); keybd_event(0x43, 0, 0, UIntPtr.Zero);
    keybd_event(0x43, 0, 2, UIntPtr.Zero); keybd_event(0x11, 0, 2, UIntPtr.Zero);
  }
}
'@
[Console]::Out.WriteLine('ready')
while ($null -ne ($line = [Console]::In.ReadLine())) { if ($line -eq 'copy') { [NexusKeys]::Copy(); [Console]::Out.WriteLine('done') } }`;

/** Presses copy in the app in front. Resolves true once pressed, false if it couldn't. */
function copier(platform, log = () => {}) {
  if (platform === 'darwin') {
    return () => new Promise((resolve) => {
      const run = spawn('/usr/bin/osascript', ['-l', 'JavaScript', '-e', MAC_COPY], { stdio: 'ignore' });
      const timer = setTimeout(() => { run.kill(); resolve(false); }, 2000);
      run.on('error', () => { clearTimeout(timer); resolve(false); });
      run.on('exit', (code) => { clearTimeout(timer); if (code) log(`Quick ask: copy failed (${code})`); resolve(code === 0); });
    });
  }
  if (platform === 'win32') {
    // Off for good once PowerShell can't run it, as where IT allows only signed scripts.
    let helper = null, waiting = [], unavailable = false;
    const answer = (ok) => { const pending = waiting; waiting = []; for (const done of pending) done(ok); };
    const start = () => {
      const script = Buffer.from(WINDOWS_COPY, 'utf16le').toString('base64');
      const powershell = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
      let ready = false;
      const child = spawn(powershell, ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', script], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
      child.stdout.setEncoding('utf8');
      child.stdout.on('data', (data) => { if (data.includes('ready')) ready = true; if (data.includes('done')) answer(true); });
      child.stderr.on('data', (data) => log(`Quick ask: ${String(data).trim()}`));
      child.on('error', (error) => { log(`Quick ask: ${error.message}`); });
      child.on('exit', (code) => {
        if (helper === child) helper = null;
        if (!ready) { unavailable = true; log(`Quick ask: selected text can't be read here (PowerShell exited with ${code})`); }
        answer(false);
      });
      return child;
    };
    const press = () => new Promise((resolve) => {
      if (unavailable) { resolve(false); return; }
      if (!helper) helper = start();
      // The first press also waits for PowerShell to start and compile.
      const done = (ok) => { clearTimeout(timer); waiting = waiting.filter((item) => item !== done); resolve(ok); };
      const timer = setTimeout(() => done(false), 4000);
      waiting.push(done);
      try { helper.stdin.write('copy\n'); } catch { answer(false); }
    });
    // Started with the app, so the first shortcut press is as quick as the rest.
    press.warm = () => { if (!helper && !unavailable) helper = start(); };
    press.stop = () => { const child = helper; helper = null; child?.kill(); };
    return press;
  }
  return async () => false;
}

/**
 * The box and its shortcut. `main()` is the app's window, `origin()` the app's address once it
 * runs, `allowed()` whether the app can open the box right now.
 */
function createQuickAsk({ BrowserWindow, globalShortcut, screen, clipboard, systemPreferences, platform, file, preload, origin, main, allowed = () => true, log = () => {}, copy = copier(platform, log) }) {
  let settings = readSettings(file), win = null, registered = null, opening = false;
  // The last press, until the page takes it: the first one can come before the page listens.
  let pending = null;

  const canReadSelection = () => platform !== 'darwin' || Boolean(systemPreferences?.isTrustedAccessibilityClient(false));
  const status = () => ({ ...settings, registered: registered === settings.shortcut, selectionAllowed: canReadSelection(), platform, visible: Boolean(win && !win.isDestroyed() && win.isVisible()) });

  function window() {
    if (win && !win.isDestroyed()) return win;
    const area = screen.getPrimaryDisplay().workArea;
    win = new BrowserWindow({ ...placement(area), show: false, frame: false, transparent: true, resizable: false, movable: false,
      minimizable: false, maximizable: false, fullscreenable: false, skipTaskbar: true, alwaysOnTop: true, hasShadow: false,
      backgroundColor: '#00000000', webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, preload, backgroundThrottling: false } });
    win.setAlwaysOnTop(true, 'floating');
    if (platform === 'darwin') win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    win.on('blur', () => { if (!opening && !win.webContents.isDevToolsOpened()) win.hide(); });
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.webContents.on('will-navigate', (event) => event.preventDefault());
    void win.loadURL(`${origin()}/quick`);
    return win;
  }

  /** Opens the box. From inside the app, as Settings' "Try it", there's no other app's selection. */
  async function open({ fromApp = false } = {}) {
    if (!allowed() || opening) return;
    const box = window();
    if (box.isVisible() && box.isFocused()) { box.hide(); return; }
    opening = true;
    try {
      // Read before the box takes focus, while the person's app is still the one in front.
      let selection = '';
      if (settings.selection && !fromApp && !box.isFocused() && canReadSelection()) {
        selection = await captureSelection({ clipboard, copy }).catch((error) => { log(`Quick ask: ${error.message}`); return ''; });
      }
      const area = screen.getDisplayNearestPoint(screen.getCursorScreenPoint()).workArea;
      box.setBounds(placement(area));
      pending = { selection, shortcut: settings.shortcut };
      box.webContents.send('nexus:quick-open', pending);
      // A moment for the page to draw the start of its entrance, or the box it last showed flashes.
      await wait(SHOW_AFTER);
      box.show(); box.focus();
    } finally { opening = false; }
  }

  function register(shortcut = settings.shortcut) {
    if (registered) { globalShortcut.unregister(registered); registered = null; }
    if (!settings.enabled) return true;
    let ok = false;
    try { ok = globalShortcut.register(shortcut, () => void open()); } catch (error) { log(`Quick ask: ${error.message}`); }
    if (ok) { registered = shortcut; window(); if (settings.selection) copy.warm?.(); } else log(`Quick ask: ${shortcut} is taken by another app`);
    return ok;
  }

  /** Changes from Settings. A shortcut another app holds is refused and the old one kept. */
  function update(change) {
    const next = { ...settings };
    if (change.shortcut !== undefined) { if (!validShortcut(change.shortcut)) return { ...status(), error: 'invalid' }; next.shortcut = change.shortcut; }
    for (const flag of ['enabled', 'selection']) if (typeof change[flag] === 'boolean') next[flag] = change[flag];
    const before = settings;
    settings = next;
    if (!register()) { settings = before; register(); return { ...status(), error: 'taken' }; }
    writeSettings(file, settings);
    return status();
  }

  function resize(height) {
    if (!win || win.isDestroyed() || !Number.isFinite(height)) return;
    win.setBounds(grow(win.getBounds(), height, screen.getDisplayMatching(win.getBounds()).workArea));
  }

  /** Shows a page of the app in its main window, and puts the box away. */
  function openInApp(link) {
    if (typeof link !== 'string' || !/^\/(?!\/)/.test(link)) return;
    win?.hide();
    const app = main();
    if (!app) return;
    void app.loadURL(origin() + link);
    app.show(); app.focus();
  }

  /** The first time closing the window leaves the app running, say where it went. */
  function noticeHidden(notify) {
    if (settings.trayNoticeShown) return;
    settings = { ...settings, trayNoticeShown: true };
    writeSettings(file, settings);
    notify(settings.enabled ? settings.shortcut : null);
  }

  return {
    isWindow: (contents) => Boolean(win && !win.isDestroyed() && contents === win.webContents),
    hide: () => win?.hide(), open,
    take: () => { const detail = pending; pending = null; return detail; }, register, update, resize, openInApp, status, noticeHidden,
    requestSelectionAccess: () => { if (platform === 'darwin') systemPreferences?.isTrustedAccessibilityClient(true); return status(); },
    dispose: () => { if (registered) globalShortcut.unregister(registered); registered = null; copy.stop?.(); },
  };
}

module.exports = { DEFAULTS, validShortcut, readSettings, writeSettings, placement, grow, captureSelection, copier, createQuickAsk, MAC_COPY };
