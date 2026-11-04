const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const yaml = require('js-yaml');
const lib = require('../release-lib.cjs');
const example = require('../release.example.json');
const { freePort, persistentFrontendPort, waitReady } = require('../runtime.cjs');
const http = require('node:http');

test('configuration rejects stored passwords, unsafe URLs and invalid server paths', () => {
  assert.equal(lib.validateConfig(structuredClone(example)).version, '0.1.0');
  for (const patch of [
    { version: '../escape' }, { updateBaseUrl: 'https://user:password@example.com/files/' },
    { updateBaseUrl: 'file:///tmp/' }, { updateBaseUrl: 'https://example.com/files' },
    { ssh: { ...example.ssh, password: 'secret' } },
    { server: { ...example.server, root: '/srv/../etc' } },
    { server: { ...example.server, port: 99999 } },
    { signing: { enabled: true } },
  ]) assert.throws(() => lib.validateConfig({ ...structuredClone(example), ...patch }));
});

test('unsigned and signed installations use different feeds', () => {
  const config = { ...example, updateBaseUrl: 'https://example.com/windows/x64/' };
  assert.equal(lib.feedUrl(config, false), 'https://example.com/windows/x64/unsigned/');
  assert.equal(lib.feedUrl(config, true), 'https://example.com/windows/x64/');
});

test('metadata points to immutable versioned artifacts and retains builder hashes', () => {
  const raw = yaml.dump({ version: '0.1.2', files: [{ url: 'Setup.exe', sha512: 'builder-hash' }], path: 'Setup.exe' });
  const result = yaml.load(lib.makeChannelMetadata(raw, '0.1.2', [{ name: 'Setup.exe' }]));
  assert.equal(result.files[0].url, '0.1.2/Setup.exe');
  assert.equal(result.files[0].sha512, 'builder-hash');
  assert.equal(result.path, '0.1.2/Setup.exe');
  assert.throws(() => lib.makeChannelMetadata(raw, '0.1.3', [{ name: 'Setup.exe' }]));
  assert.throws(() => lib.makeChannelMetadata(raw, '0.1.2', [{ name: 'Other.exe' }]));
});

test('changed artifacts and traversal filenames cannot be published', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'nexusai-release-'));
  try {
    const files = [];
    for (const name of ['Setup.exe', 'latest.yml']) {
      await fs.writeFile(path.join(directory, name), 'original');
      files.push({ name, size: 8, sha256: await lib.sha256(path.join(directory, name)) });
    }
    const manifest = { version: '0.1.0', files };
    await lib.verifyArtifacts(directory, manifest);
    await fs.writeFile(path.join(directory, 'Setup.exe'), 'modified');
    await assert.rejects(lib.verifyArtifacts(directory, manifest), /corrupted/);
    await assert.rejects(lib.verifyArtifacts(directory, { ...manifest, files: [{ name: '../outside' }, files[1]] }), /filename/);
  } finally { await fs.rm(directory, { recursive: true, force: true }); }
});

test('readiness waits for a listening service and rejects a dead child', async () => {
  const port = await freePort();
  const server = http.createServer((_, response) => response.end('ready'));
  await new Promise((resolve) => server.listen(port, '127.0.0.1', resolve));
  try {
    await waitReady(`http://127.0.0.1:${port}`, { exitCode: null, signalCode: null }, 2000);
    await assert.rejects(waitReady(`http://127.0.0.1:${port}`, { exitCode: 1, signalCode: null }), /exited/);
  } finally { await new Promise((resolve) => server.close(resolve)); }
});

test('the frontend origin remains stable across launches and a collision is actionable', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'nexusai-origin-'));
  let server;
  try {
    const first = await persistentFrontendPort(directory);
    assert.equal(await persistentFrontendPort(directory), first);
    server = http.createServer();
    await new Promise((resolve) => server.listen(first, '127.0.0.1', resolve));
    await assert.rejects(persistentFrontendPort(directory), /saved local port.*in use/);
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    await fs.rm(directory, { recursive: true, force: true });
  }
});
