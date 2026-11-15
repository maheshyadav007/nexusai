const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const quick = require('../quick-ask.cjs');

const area = { x: 0, y: 25, width: 1440, height: 875 };
const tempFile = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'nexusai-quick-')), 'quick-ask.json');

test('shortcuts need a modifier other than Shift and exactly one key', () => {
  for (const good of ['Control+Alt+Space', 'Command+Shift+K', 'Super+Alt+P', 'Alt+F2', 'Control+Shift+/']) assert.ok(quick.validShortcut(good), good);
  for (const bad of ['Space', 'Shift+A', 'Control+Control+A', 'Control+Alt', 'Control+A+B', 'Hyper+A', '', null, 'Control+' + 'A'.repeat(70)]) assert.ok(!quick.validShortcut(bad), String(bad));
});

test('settings fall back to the defaults when missing or damaged', () => {
  const file = tempFile();
  assert.deepEqual(quick.readSettings(file), quick.DEFAULTS);
  fs.writeFileSync(file, '{ not json');
  assert.deepEqual(quick.readSettings(file), quick.DEFAULTS);
  fs.writeFileSync(file, JSON.stringify({ shortcut: 'Shift+A', enabled: 'yes', selection: false }));
  assert.deepEqual(quick.readSettings(file), { ...quick.DEFAULTS, selection: false });
  quick.writeSettings(file, { ...quick.DEFAULTS, shortcut: 'Alt+Q' });
  assert.equal(quick.readSettings(file).shortcut, 'Alt+Q');
});

test('the box sits at the bottom centre of the usable area and grows upward', () => {
  const start = quick.placement(area);
  assert.deepEqual(start, { x: 340, y: 25 + 875 - 96 - 24, width: 760, height: 96 });
  const taller = quick.grow(start, 400, area);
  assert.equal(taller.y + taller.height, start.y + start.height);
  assert.equal(taller.height, 400);
  assert.equal(quick.grow(start, 5000, area).height, 640);
  assert.equal(quick.grow(start, 10, area).height, 96);
  const small = { x: 0, y: 0, width: 500, height: 300 };
  assert.ok(quick.placement(small).width <= 500);
  assert.ok(quick.grow(quick.placement(small), 900, small).y >= 0);
});

function fakeClipboard(initial) {
  const board = { text: initial.text ?? '', html: initial.html ?? '', rtf: '', image: { isEmpty: () => true } };
  return {
    board,
    readText: () => board.text, readHTML: () => board.html, readRTF: () => board.rtf, readImage: () => board.image,
    writeText: (text) => { board.text = text; board.html = ''; },
    write: (data) => { board.text = data.text ?? ''; board.html = data.html ?? ''; },
    clear: () => { board.text = ''; board.html = ''; },
  };
}
const wait = () => Promise.resolve();
const press = async (run) => { run(); await new Promise((resolve) => setTimeout(resolve, 100)); };

test('the selection is read and the clipboard is given back as it was', async () => {
  const clipboard = fakeClipboard({ text: 'what the person copied', html: '<b>what the person copied</b>' });
  const copy = async () => { clipboard.board.text = '  The PLM release moves to Friday.  '; return true; };
  assert.equal(await quick.captureSelection({ clipboard, copy, wait }), 'The PLM release moves to Friday.');
  assert.equal(clipboard.board.text, 'what the person copied');
  assert.equal(clipboard.board.html, '<b>what the person copied</b>');
});

test('nothing selected gives an empty selection, even when the clipboard already held text', async () => {
  const clipboard = fakeClipboard({ text: 'old text' });
  assert.equal(await quick.captureSelection({ clipboard, copy: async () => true, wait, timeout: 40 }), '');
  assert.equal(clipboard.board.text, 'old text');
  // Copy keys that couldn't be pressed, such as without Accessibility on a Mac.
  assert.equal(await quick.captureSelection({ clipboard, copy: async () => false, wait }), '');
  assert.equal(clipboard.board.text, 'old text');
});

test('a failed copy still gives the clipboard back, and an empty one stays empty', async () => {
  const clipboard = fakeClipboard({});
  await assert.rejects(quick.captureSelection({ clipboard, copy: async () => { throw new Error('boom'); }, wait }));
  assert.equal(clipboard.board.text, '');
});

test('nothing is written to the clipboard when the copy changes nothing, so clipboard history stays clean', async () => {
  const clipboard = fakeClipboard({ text: 'old text' });
  let writes = 0;
  clipboard.writeText = () => { writes++; }; clipboard.write = () => { writes++; }; clipboard.clear = () => { writes++; };
  assert.equal(await quick.captureSelection({ clipboard, copy: async () => true, wait, timeout: 40 }), '');
  assert.equal(writes, 0);
});

test('a long selection is cut to a size a message can carry', async () => {
  const clipboard = fakeClipboard({});
  const copy = async () => { clipboard.board.text = 'x'.repeat(20000); return true; };
  assert.equal((await quick.captureSelection({ clipboard, copy, wait })).length, 8000);
});

function fakes({ taken = [] } = {}) {
  const held = new Map();
  const shown = [];
  class Win {
    constructor(options) { this.bounds = { x: options.x, y: options.y, width: options.width, height: options.height }; this.visible = false; this.focused = false; this.events = {};
      this.webContents = { sent: [], send: (channel, data) => this.webContents.sent.push([channel, data]), setWindowOpenHandler() {}, on() {}, isDevToolsOpened: () => false }; }
    setAlwaysOnTop() {} setVisibleOnAllWorkspaces() {} loadURL(url) { this.url = url; return Promise.resolve(); }
    on(name, handler) { this.events[name] = handler; } isDestroyed() { return false; } isVisible() { return this.visible; } isFocused() { return this.focused; }
    show() { this.visible = true; shown.push(this); } focus() { this.focused = true; } hide() { this.visible = false; this.focused = false; }
    setBounds(bounds) { this.bounds = bounds; } getBounds() { return this.bounds; }
  }
  return {
    held, shown,
    BrowserWindow: Win,
    globalShortcut: { register: (key, run) => { if (taken.includes(key)) return false; held.set(key, run); return true; }, unregister: (key) => held.delete(key) },
    screen: { getPrimaryDisplay: () => ({ workArea: area }), getCursorScreenPoint: () => ({ x: 10, y: 10 }), getDisplayNearestPoint: () => ({ workArea: area }), getDisplayMatching: () => ({ workArea: area }) },
  };
}

test('the shortcut opens the box with the selection, and pressing it again puts it away', async () => {
  const electron = fakes();
  const clipboard = fakeClipboard({ text: 'kept' });
  const copy = async () => { clipboard.board.text = 'selected words'; return true; };
  const box = quick.createQuickAsk({ ...electron, clipboard, platform: 'win32', file: tempFile(), preload: 'preload.cjs', origin: () => 'http://127.0.0.1:4001', main: () => null, copy });
  assert.ok(box.register());
  // Loaded with the shortcut, so the first press doesn't wait for the page.
  assert.ok(!electron.shown.length);
  await press(electron.held.get('Control+Alt+Space'));
  const win = electron.shown[0];
  assert.equal(win.url, 'http://127.0.0.1:4001/quick');
  assert.deepEqual(win.webContents.sent.at(-1), ['nexus:quick-open', { selection: 'selected words', shortcut: 'Control+Alt+Space' }]);
  assert.equal(clipboard.board.text, 'kept');
  assert.ok(win.visible && win.focused);
  // A page that wasn't listening yet takes the press once it is.
  assert.deepEqual(box.take(), { selection: 'selected words', shortcut: 'Control+Alt+Space' });
  assert.equal(box.take(), null);
  assert.ok(box.isWindow(win.webContents));
  box.resize(300);
  assert.equal(win.bounds.height, 300);
  await press(electron.held.get('Control+Alt+Space'));
  assert.ok(!win.visible);
});

test('a shortcut another app holds is refused and the old one keeps working', () => {
  const electron = fakes({ taken: ['Alt+Space'] });
  const file = tempFile();
  const box = quick.createQuickAsk({ ...electron, clipboard: fakeClipboard({}), platform: 'win32', file, preload: '', origin: () => '', main: () => null, copy: async () => false });
  box.register();
  assert.equal(box.update({ shortcut: 'Alt+Space' }).error, 'taken');
  assert.ok(electron.held.has('Control+Alt+Space'));
  assert.equal(box.update({ shortcut: 'Space' }).error, 'invalid');
  const saved = box.update({ shortcut: 'Control+Shift+K' });
  assert.equal(saved.error, undefined);
  assert.ok(saved.registered);
  assert.ok(electron.held.has('Control+Shift+K') && !electron.held.has('Control+Alt+Space'));
  assert.equal(quick.readSettings(file).shortcut, 'Control+Shift+K');
  assert.ok(!box.update({ enabled: false }).registered);
  assert.equal(electron.held.size, 0);
});

test('without Accessibility on a Mac the box opens without reading the selection', async () => {
  const electron = fakes();
  let pressed = false;
  const box = quick.createQuickAsk({ ...electron, clipboard: fakeClipboard({}), systemPreferences: { isTrustedAccessibilityClient: () => false }, platform: 'darwin',
    file: tempFile(), preload: '', origin: () => '', main: () => null, copy: async () => { pressed = true; return true; } });
  box.register();
  await box.open();
  assert.ok(!pressed);
  assert.equal(box.status().selectionAllowed, false);
  assert.equal(electron.shown[0].webContents.sent.at(-1)[1].selection, '');
});

test("Try it from Settings opens the box without pressing copy in NexusAI's own window", async () => {
  const electron = fakes();
  let pressed = false;
  const box = quick.createQuickAsk({ ...electron, clipboard: fakeClipboard({}), platform: 'win32', file: tempFile(), preload: '', origin: () => '', main: () => null, copy: async () => { pressed = true; return true; } });
  box.register();
  await box.open({ fromApp: true });
  assert.ok(!pressed);
  assert.ok(electron.shown[0].visible);
});

test('the tray notice is shown once', () => {
  const box = quick.createQuickAsk({ ...fakes(), clipboard: fakeClipboard({}), platform: 'win32', file: tempFile(), preload: '', origin: () => '', main: () => null, copy: async () => false });
  const notices = [];
  box.noticeHidden((shortcut) => notices.push(shortcut));
  box.noticeHidden((shortcut) => notices.push(shortcut));
  assert.deepEqual(notices, ['Control+Alt+Space']);
});

test('only app pages open in the main window', () => {
  const loaded = [];
  const app = { loadURL: (url) => { loaded.push(url); return Promise.resolve(); }, show() {}, focus() {} };
  const box = quick.createQuickAsk({ ...fakes(), clipboard: fakeClipboard({}), platform: 'win32', file: tempFile(), preload: '', origin: () => 'http://127.0.0.1:4001', main: () => app, copy: async () => false });
  box.openInApp('//evil.example');
  box.openInApp('https://evil.example');
  box.openInApp('/agent/sessions/12?view=full');
  assert.deepEqual(loaded, ['http://127.0.0.1:4001/agent/sessions/12?view=full']);
});
