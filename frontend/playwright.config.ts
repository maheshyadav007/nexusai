import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

// Workers reload this file, so they must find the same folder as the servers.
const home = (process.env.E2E_HOME ??= mkdtempSync(join(tmpdir(), "nexusai-e2e-")));

export default defineConfig({
  testDir: "e2e",
  // first-run.spec.ts runs first and sets up the Home the others use.
  workers: 1,
  // Reduced motion keeps colors from being measured halfway through a transition.
  use: { baseURL: "http://127.0.0.1:4000", contextOptions: { reducedMotion: "reduce" } },
  webServer: [
    // A fake ChatGPT and a test secrets file, so tests never reach a real account or the Keychain.
    { command: "uv run --quiet python tests/fake_chatgpt.py", cwd: "../backend", url: "http://127.0.0.1:8766/docs", env: { VIRTUAL_ENV: "" }, reuseExistingServer: false },
    { command: "uv run --quiet python tests/fake_mail.py", cwd: "../backend", url: "http://127.0.0.1:8767/", env: { VIRTUAL_ENV: "" }, reuseExistingServer: false },
    { command: "uv run --quiet nexusai-backend", cwd: "../backend", url: "http://127.0.0.1:4100/api/health", env: { NEXUSAI_LEARN_EMAILS: "0", NEXUSAI_APP_DATA: join(home, "app-data"), VIRTUAL_ENV: "", NEXUSAI_MODEL_HUB: "http://127.0.0.1:9", NEXUSAI_CHATGPT_ISSUER: "http://127.0.0.1:8766", NEXUSAI_CHATGPT_BASE_URL: "http://127.0.0.1:8766/codex", NEXUSAI_SECRETS_TEST_FILE: join(home, "secrets.json") }, reuseExistingServer: false },
    { command: "npm run dev", url: "http://127.0.0.1:4000/gallery", env: { NEXUSAI_APP_DATA: join(home, "app-data") }, reuseExistingServer: false, timeout: 120_000 },
  ],
});
