const { Client, utils } = require('ssh2');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline/promises');
const crypto = require('node:crypto');

async function ask(question, fallback = '') {
  const terminal = readline.createInterface({ input: process.stdin, output: process.stdout });
  try { return (await terminal.question(`${question}${fallback ? ` [${fallback}]` : ''}: `)).trim() || fallback; }
  finally { terminal.close(); }
}

async function secret(question) {
  if (!process.stdin.isTTY || !process.stdin.setRawMode) throw new Error('Run this command in an interactive terminal to enter a password.');
  process.stdout.write(`${question}: `);
  const input = process.stdin;
  input.setRawMode(true); input.resume(); input.setEncoding('utf8');
  return new Promise((resolve, reject) => {
    let value = '';
    function finish(error) {
      input.removeListener('data', onData); input.setRawMode(false); input.pause();
      process.stdout.write('\n');
      if (error) reject(error); else resolve(value);
    }
    function onData(data) {
      for (const char of data) {
        if (char === '\u0003') return finish(new Error('Cancelled.'));
        if (char === '\r' || char === '\n') return finish();
        if (char === '\u007f' || char === '\b') value = value.slice(0, -1);
        else if (char >= ' ') value += char;
      }
    }
    input.on('data', onData);
  });
}

async function connect(config, localDirectory) {
  const knownFile = path.join(localDirectory, 'known-hosts.json');
  const known = fs.existsSync(knownFile) ? JSON.parse(fs.readFileSync(knownFile, 'utf8')) : {};
  const identity = `${config.host}:${config.port}`;
  const options = { host: config.host, port: config.port, username: config.username, readyTimeout: 30000,
    keepaliveInterval: 10000, keepaliveCountMax: 3,
    hostVerifier(key, callback) {
      const fingerprint = `SHA256:${crypto.createHash('sha256').update(key).digest('base64').replace(/=+$/, '')}`;
      if (known[identity]) { callback(known[identity] === fingerprint); return; }
      console.log(`SSH host ${identity}\nHost key: ${fingerprint}`);
      void ask('Trust this host key? Verify it with your server administrator or server console; type yes', 'no').then((answer) => {
        if (answer !== 'yes') return callback(false);
        known[identity] = fingerprint;
        fs.mkdirSync(localDirectory, { recursive: true });
        fs.writeFileSync(knownFile, JSON.stringify(known, null, 2)); callback(true);
      }).catch(() => callback(false));
    },
  };
  if (config.privateKeyFile) {
    options.privateKey = fs.readFileSync(config.privateKeyFile);
    const parsed = utils.parseKey(options.privateKey);
    if (parsed instanceof Error) {
      if (/encrypted|passphrase/i.test(parsed.message)) options.passphrase = await secret('SSH key passphrase');
      else throw parsed;
    }
  } else options.password = await secret(`SSH password for ${config.username}@${config.host}`);
  const client = new Client();
  await new Promise((resolve, reject) => { client.once('ready', resolve); client.once('error', reject); client.connect(options); });
  return client;
}

function exec(client, command, input = '') {
  return new Promise((resolve, reject) => {
    client.exec(command, (error, stream) => {
      if (error) return reject(error);
      let output = '';
      stream.on('data', (chunk) => { output += chunk; process.stdout.write(chunk); });
      stream.stderr.on('data', (chunk) => { output += chunk; process.stderr.write(chunk); });
      stream.on('error', reject);
      stream.on('close', (code) => code === 0 ? resolve(output) : reject(new Error(`Remote command failed (${code}).`)));
      stream.end(input);
    });
  });
}

function sftp(client) { return new Promise((resolve, reject) => client.sftp((error, session) => error ? reject(error) : resolve(session))); }
function put(session, local, remote) { return new Promise((resolve, reject) => session.fastPut(local, remote, (error) => error ? reject(error) : resolve())); }
module.exports = { ask, secret, connect, exec, sftp, put };
