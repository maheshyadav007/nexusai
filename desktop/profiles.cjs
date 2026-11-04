const fs = require('node:fs');
const path = require('node:path');
const Zip = require('adm-zip');
const { validateConfig } = require('./release-lib.cjs');

const publicKeys = new Set([
  'NEXUSAI_MAIL_LABEL', 'NEXUSAI_MAIL_PROTOCOL', 'NEXUSAI_MAIL_HOST', 'NEXUSAI_MAIL_PORT',
  'NEXUSAI_MAIL_SECURE', 'NEXUSAI_MAIL_VERIFY_CERT', 'NEXUSAI_MAIL_DOMAIN',
  'NEXUSAI_SMTP_HOST', 'NEXUSAI_SMTP_PORT', 'NEXUSAI_SMTP_SECURE',
  'NEXUSAI_MODEL_URL', 'NEXUSAI_MODEL_NAMES', 'NEXUSAI_MODEL_TOOLS',
  'NEXUSAI_MODEL_CALLS_PER_MINUTE',
]);

function deploymentDefaults(text, embedCredentials = false) {
  if (embedCredentials) return text;
  return text.split(/\r?\n/).filter((line) => {
    const match = line.trim().replace(/^export\s+/, '').match(/^([A-Z0-9_]+)\s*=/);
    return match && publicKeys.has(match[1]);
  }).join('\n') + '\n';
}

function initProfile(root, directory) {
  fs.mkdirSync(directory, { recursive: true });
  const config = path.join(directory, 'release.json');
  const env = path.join(directory, 'company.env');
  if (!fs.existsSync(config)) {
    const example = JSON.parse(fs.readFileSync(path.join(root, 'desktop/release.example.json'), 'utf8'));
    example.companyEnvFile = 'company.env';
    fs.writeFileSync(config, JSON.stringify(example, null, 2));
  }
  if (!fs.existsSync(env)) fs.copyFileSync(path.join(root, 'deployment/company.example.env'), env);
  console.log(`Edit these local files:\n${config}\n${env}\nThen run desktop.sh prepare-profile (or desktop.cmd prepare-profile).`);
}

function prepareProfile(directory, output, sourceCommit) {
  const config = validateConfig(JSON.parse(fs.readFileSync(path.join(directory, 'release.json'), 'utf8').replace(/^\uFEFF/, '')));
  const archive = new Zip();
  for (const [object, key, name] of [[config, 'companyEnvFile', 'company.env'],
    [config.signing, 'certificateFile', 'signing.pfx'], [config.ssh, 'privateKeyFile', 'ssh-key']]) {
    if (!object[key]) continue;
    const source = path.resolve(directory, object[key]);
    archive.addFile(name, fs.readFileSync(source));
    object[key] = name;
  }
  archive.addFile('release.json', Buffer.from(JSON.stringify(config, null, 2)));
  archive.addFile('source.json', Buffer.from(JSON.stringify({ schemaVersion: 1, sourceCommit }, null, 2)));
  fs.mkdirSync(path.dirname(output), { recursive: true });
  archive.writeZip(output);
  console.log(`Prepared deployment bundle: ${output}\nTransfer this private bundle to the build machine; do not add it to Git or public CI artifacts.`);
}

function applyProfile(archivePath, target, configFile) {
  const archive = new Zip(archivePath);
  const allowed = new Set(['release.json', 'source.json', 'company.env', 'signing.pfx', 'ssh-key']);
  const entries = archive.getEntries();
  if (entries.length > allowed.size || new Set(entries.map((entry) => entry.entryName)).size !== entries.length) throw new Error('Invalid deployment bundle.');
  if (!entries.some((entry) => entry.entryName === 'release.json')) throw new Error('Deployment bundle has no release.json.');
  for (const entry of entries) if (!allowed.has(entry.entryName) || entry.isDirectory) throw new Error('Unexpected file in deployment bundle.');
  const config = validateConfig(JSON.parse(archive.readAsText('release.json')));
  for (const [object, key] of [[config, 'companyEnvFile'], [config.signing, 'certificateFile'], [config.ssh, 'privateKeyFile']]) {
    if (object[key]) {
      if (!allowed.has(object[key]) || !entries.some((entry) => entry.entryName === object[key])) throw new Error('Deployment bundle references a missing or external file.');
      object[key] = path.join(target, object[key]);
    }
  }
  fs.mkdirSync(target, { recursive: true });
  for (const entry of entries) fs.writeFileSync(path.join(target, entry.entryName), entry.getData(), { mode: 0o600 });
  fs.writeFileSync(configFile, JSON.stringify(config, null, 2), { mode: 0o600 });
  console.log('Deployment profile applied locally. Next: desktop.cmd build-test.');
}

module.exports = { deploymentDefaults, initProfile, prepareProfile, applyProfile };
