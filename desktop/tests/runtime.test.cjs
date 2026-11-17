const { test } = require('node:test');
const assert = require('node:assert/strict');
const { PYTHON_FLAGS, serviceEnv } = require('../runtime.cjs');

test('bundled services ignore the Python, Node and NexusAI set up on the computer', () => {
  const computer = { PATH: 'C:\\Windows', PYTHONHOME: 'C:\\Python313', NODE_OPTIONS: '--require x', node_path: 'C:\\n', NEXUSAI_HOME: 'C:\\dev', SSL_CERT_FILE: 'C:\\ca.pem' };
  assert.deepEqual(serviceEnv(computer, true), { PATH: 'C:\\Windows', PYTHONHOME: 'C:\\Python313', SSL_CERT_FILE: 'C:\\ca.pem' });
  assert.equal(serviceEnv(computer, false).NEXUSAI_HOME, 'C:\\dev');
  // PYTHON* stays for the person's own commands; our Python ignores it because of -I.
  assert.ok(PYTHON_FLAGS.includes('-I'));
});
