const net = require('node:net');
const fs = require('node:fs/promises');
const path = require('node:path');

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

async function persistentFrontendPort(directory) {
  const file = path.join(directory, 'frontend-port');
  let port;
  try { port = Number((await fs.readFile(file, 'utf8')).trim()); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (port === undefined) {
    port = await freePort();
    await fs.writeFile(file, String(port), { mode: 0o600 });
  }
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid saved frontend port. Inspect frontend-port in the app-data directory.');
  await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', () => reject(new Error(`NexusAI's saved local port ${port} is in use. Close the other instance/application or restart Windows. The port is preserved to keep browser storage available.`)));
    server.listen(port, '127.0.0.1', () => server.close(resolve));
  });
  return port;
}

async function waitReady(url, child, timeout = 120000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (child.spawnError) throw child.spawnError;
    if (child.exitCode !== null || child.signalCode !== null) throw new Error(`Service exited before ready: ${url}`);
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (response.ok) return;
    } catch { /* A service may still be opening a Home or compiling its startup state. */ }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Timed out waiting for ${url}. Open desktop.log for details.`);
}

function waitExit(child, timeout = 120000) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return Promise.resolve(child?.exitCode);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      child.removeListener('exit', done);
      reject(new Error('Backend is still stopping. No update was installed. Wait and try again.'));
    }, timeout);
    function done(code) { clearTimeout(timer); resolve(code); }
    child.once('exit', done);
  });
}

module.exports = { freePort, persistentFrontendPort, waitReady, waitExit };
