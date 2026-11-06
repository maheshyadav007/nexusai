const net = require('node:net');
const fs = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { createHash } = require('node:crypto');
const { createReadStream } = require('node:fs');

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

function isAlive(child) { return Boolean(child && child.exitCode === null && child.signalCode === null && !child.spawnError); }

function waitExit(child, timeout = 120000, name = 'Service') {
  const result = () => {
    if (child?.spawnError) throw child.spawnError;
    if (child?.signalCode) throw new Error(`${name} stopped unexpectedly (${child.signalCode}). No update was installed.`);
    return child?.exitCode;
  };
  if (!isAlive(child)) return Promise.resolve().then(result);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      child.removeListener('exit', done);
      reject(new Error(`${name} is still stopping. No update was installed. Wait and retry the shutdown.`));
    }, timeout);
    function done(code, signal) {
      clearTimeout(timer);
      if (signal) reject(new Error(`${name} stopped unexpectedly (${signal}). No update was installed.`));
      else resolve(code);
    }
    child.once('exit', done);
  });
}

async function verifyInstaller(update) {
  if (!update || !path.isAbsolute(update.file) || !update.file.toLowerCase().endsWith('.exe') || typeof update.sha512 !== 'string') {
    throw new Error('No verified update installer is ready. Download the update again.');
  }
  const hash = createHash('sha512');
  for await (const chunk of createReadStream(update.file)) hash.update(chunk);
  if (hash.digest('base64') !== update.sha512) throw new Error('The downloaded installer changed. Download the update again.');
}

async function launchInstaller(update, spawnProcess = spawn) {
  await verifyInstaller(update);
  await new Promise((resolve, reject) => {
    const installer = spawnProcess(update.file, ['--updated', '/S', '--force-run'], { detached: true, stdio: 'ignore', windowsHide: true });
    installer.once('error', reject);
    installer.once('spawn', () => { installer.unref(); resolve(); });
  });
}

// Runs a downloaded, checksum-verified installer silently and returns its exit code. With the side-by-side
// layout this happens while NexusAI keeps running: the installer only adds and activates a version folder.
async function runInstaller(update, spawnProcess = spawn, timeout = 20 * 60 * 1000) {
  await verifyInstaller(update);
  return new Promise((resolve, reject) => {
    const installer = spawnProcess(update.file, ['--updated', '/S'], { stdio: 'ignore', windowsHide: true });
    const timer = setTimeout(() => reject(new Error('The update installer did not finish within 20 minutes. Details: %TEMP%\\nexusai-setup.log')), timeout);
    installer.once('error', error => { clearTimeout(timer); reject(error); });
    installer.once('exit', code => { clearTimeout(timer); resolve(code); });
  });
}

function waitInstalledServices(resources, executable, spawnProcess = spawn) {
  return new Promise((resolve, reject) => {
    const powershell = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32/WindowsPowerShell/v1.0/powershell.exe');
    const child = spawnProcess(powershell, ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', path.join(resources, 'check-install.ps1'),
      '-InstallDirectory', path.dirname(executable), '-AppGuid', '00000000-0000-0000-0000-000000000000', '-Version', '0.0.0', '-Mode', 'services'], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    const collect = chunk => { output = (output + String(chunk)).slice(-8000); };
    child.stdout.on('data', collect); child.stderr.on('data', collect);
    const timer = setTimeout(() => { child.kill(); reject(new Error('The local-service check timed out. No update was installed.')); }, 135000);
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('exit', code => { clearTimeout(timer); code === 0 ? resolve() : reject(new Error(output.trim() || 'Local services have not stopped. No update was installed.')); });
  });
}

module.exports = { freePort, persistentFrontendPort, waitReady, waitExit, isAlive, launchInstaller, runInstaller, waitInstalledServices };
