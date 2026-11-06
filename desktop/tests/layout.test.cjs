const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const layout = require('../layout.cjs');

const exe = 'NexusAI Beta.exe';
async function tree(files) {
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), 'nexusai-layout-'));
  for (const [relative, content] of Object.entries(files)) {
    await fsp.mkdir(path.dirname(path.join(root, relative)), { recursive: true });
    await fsp.writeFile(path.join(root, relative), content);
  }
  return root;
}
const version = (v, extra = {}) => ({ [`app-${v}/${exe}`]: '', [`app-${v}/.nexusai-complete`]: v, ...extra });
const pointer = v => ({ 'nexusai-install.ini': `﻿[Install]\r\nFormat=1\r\nCurrent=${v}\r\n` });
const names = root => fs.readdirSync(root).sort();
const quiet = () => {};

test('only an app-x.y.z folder next to the version pointer is a side-by-side installation', async () => {
  const root = await tree({ ...pointer('0.2.0'), ...version('0.2.0'), [`win-unpacked/${exe}`]: '' });
  try {
    assert.equal(layout.installRoot(path.join(root, 'app-0.2.0', exe)), root);
    assert.equal(layout.installRoot(path.join(root, 'win-unpacked', exe)), null);
    fs.rmSync(path.join(root, 'nexusai-install.ini'));
    assert.equal(layout.installRoot(path.join(root, 'app-0.2.0', exe)), null);
  } finally { await fsp.rm(root, { recursive: true, force: true }); }
});

test('the pointer is read defensively', async () => {
  const root = await tree({});
  try {
    for (const [content, expected] of [
      ['[Install]\nCurrent=0.3.1\n', '0.3.1'], ['[Install]\r\ncurrent = 0.3.1 \r\n', '0.3.1'],
      ['[Install]\nCurrent=..\\..\\Windows\n', null], ['[Install]\nCurrent=0.3\n', null], ['', null],
    ]) {
      fs.writeFileSync(path.join(root, 'nexusai-install.ini'), content);
      assert.equal(layout.activeVersion(root), expected, JSON.stringify(content));
    }
    fs.rmSync(path.join(root, 'nexusai-install.ini'));
    assert.equal(layout.activeVersion(root), null);
  } finally { await fsp.rm(root, { recursive: true, force: true }); }
});

test('a newer version counts as pending only when it is active and complete', async () => {
  const root = await tree({ ...pointer('0.2.1'), ...version('0.2.0'), [`app-0.2.1/${exe}`]: '' });
  try {
    assert.equal(layout.pendingVersion(root, '0.2.0', exe), null, 'no completion marker yet');
    fs.writeFileSync(path.join(root, 'app-0.2.1', '.nexusai-complete'), '0.2.1');
    assert.equal(layout.pendingVersion(root, '0.2.0', exe), '0.2.1');
    assert.equal(layout.pendingVersion(root, '0.2.1', exe), null);
    assert.equal(layout.pendingVersion(root, '0.3.0', exe), null, 'never offers an older version');
  } finally { await fsp.rm(root, { recursive: true, force: true }); }
});

test('cleanup keeps running, active and newer versions and removes the rest', async () => {
  const root = await tree({ ...pointer('0.2.1'), ...version('0.1.0'), ...version('0.2.0'), ...version('0.2.1'), ...version('0.3.0'),
    'app-0.1.5/partial.dll': '', '.trash-app-0.0.9-x/left.dll': '', 'logs/launcher.log': '' });
  try {
    const result = await layout.cleanup(root, '0.2.0', quiet);
    assert.deepEqual(result, { '.trash-app-0.0.9-x': 'removed', 'app-0.1.0': 'removed', 'app-0.1.5': 'removed' });
    assert.deepEqual(names(root), ['app-0.2.0', 'app-0.2.1', 'app-0.3.0', 'logs', 'nexusai-install.ini']);
  } finally { await fsp.rm(root, { recursive: true, force: true }); }
});

test('a locked old version is kept and retried on the next pass', async () => {
  const root = await tree({ ...pointer('0.2.0'), ...version('0.1.0'), ...version('0.2.0') });
  const lines = [];
  const realRename = fsp.rename;
  try {
    // On Windows, renaming fails while a file inside is open; simulate that refusal.
    fsp.rename = async (from, to) => { if (path.basename(from) === 'app-0.1.0') { const error = new Error('busy'); error.code = 'EBUSY'; throw error; } return realRename(from, to); };
    assert.deepEqual(await layout.cleanup(root, '0.2.0', line => lines.push(line)), { 'app-0.1.0': 'kept' });
    assert.match(lines.join('\n'), /kept .*app-0\.1\.0.*EBUSY/);
    fsp.rename = realRename;
    assert.deepEqual(await layout.cleanup(root, '0.2.0', quiet), { 'app-0.1.0': 'removed' });
  } finally { fsp.rename = realRename; await fsp.rm(root, { recursive: true, force: true }); }
});

test('an installer staging folder is left alone until it is clearly abandoned', async () => {
  const root = await tree({ ...pointer('0.2.0'), ...version('0.2.0'), '.staging-0.2.0-123/x.dll': '' });
  try {
    assert.deepEqual(await layout.cleanup(root, '0.2.0', quiet), {});
    assert.deepEqual(await layout.cleanup(root, '0.2.0', quiet, Date.now() + 7 * 60 * 60 * 1000), { '.staging-0.2.0-123': 'removed' });
  } finally { await fsp.rm(root, { recursive: true, force: true }); }
});

test('leftovers of the old single-folder layout are removed by their recorded names only', async () => {
  const root = await tree({ ...pointer('0.2.0'), ...version('0.2.0'), [exe]: 'launcher', [`Uninstall ${exe}`]: '',
    'resources/app.asar': '', 'locales/en-US.pak': '', 'ffmpeg.dll': '', 'user-notes.txt': 'not ours',
    '.legacy-files': 'resources\r\nlocales\r\nffmpeg.dll\r\n..\\outside\r\napp-0.2.0\r\nnexusai-install.ini\r\nsomething.exe\r\nmissing.dll\r\n' });
  try {
    const result = await layout.cleanup(root, '0.2.0', quiet);
    assert.equal(result['.legacy-files'], 'removed');
    assert.deepEqual(names(root), [exe, `Uninstall ${exe}`, 'app-0.2.0', 'nexusai-install.ini', 'user-notes.txt']);
  } finally { await fsp.rm(root, { recursive: true, force: true }); }
});

test('installer exit codes become actionable messages with the code and log', () => {
  assert.match(layout.installerError(22), /not enough free disk space.*NX-22.*nexusai-setup\.log/);
  assert.match(layout.installerError(999), /could not be installed.*NX-999/);
  assert.equal(layout.compareVersions('0.10.0', '0.9.9') > 0, true);
});
