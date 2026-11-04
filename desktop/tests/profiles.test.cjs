const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const profiles = require('../profiles.cjs');
const Zip = require('adm-zip');

test('deployment defaults exclude credential fields unless explicitly embedded', () => {
  const input = 'NEXUSAI_MAIL_HOST=mail.example.test\nNEXUSAI_MODEL_URL=https://model.example.test\nNEXUSAI_MODEL_API_KEY=private\nOTHER_SECRET=hidden\n';
  const defaults = profiles.deploymentDefaults(input);
  assert.match(defaults, /mail.example.test/);
  assert.match(defaults, /model.example.test/);
  assert.doesNotMatch(defaults, /private|hidden|API_KEY/);
  assert.equal(profiles.deploymentDefaults(input, true), input);
});

test('deployment profile round-trip relocates local settings', () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'nexusai-profile-'));
  try {
    const source = path.join(temporary, 'linux-profile');
    profiles.initProfile(path.resolve(__dirname, '../..'), source);
    fs.writeFileSync(path.join(source, 'company.env'), 'NEXUSAI_MAIL_HOST=internal.example.test\n');
    const archive = path.join(temporary, 'deployment.zip');
    profiles.prepareProfile(source, archive, 'source-commit');
    const target = path.join(temporary, 'windows-profile');
    const config = path.join(temporary, 'release.local.json');
    profiles.applyProfile(archive, target, config);
    const applied = JSON.parse(fs.readFileSync(config, 'utf8'));
    assert.equal(applied.companyEnvFile, path.join(target, 'company.env'));
    assert.match(fs.readFileSync(applied.companyEnvFile, 'utf8'), /internal.example.test/);
    const bad = new Zip();
    bad.addFile('unexpected.txt', Buffer.from('no'));
    const badFile = path.join(temporary, 'bad.zip'); bad.writeZip(badFile);
    assert.throws(() => profiles.applyProfile(badFile, target, config), /no release.json|Unexpected/);
  } finally { fs.rmSync(temporary, { recursive: true, force: true }); }
});
