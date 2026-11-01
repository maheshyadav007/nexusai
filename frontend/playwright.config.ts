import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

const home = mkdtempSync(join(tmpdir(), "nexusai-e2e-"));

export default defineConfig({
  testDir: "e2e",
  use: { baseURL: "http://127.0.0.1:3000" },
  webServer: [
    // A fake ChatGPT and a test secrets file, so tests never reach a real account or the Keychain.
    { command: "uv run --quiet python tests/fake_chatgpt.py", cwd: "../backend", url: "http://127.0.0.1:8766/docs", env: { VIRTUAL_ENV: "" }, reuseExistingServer: false },
    { command: "uv run --quiet nexusai-backend", cwd: "../backend", url: "http://127.0.0.1:8765/api/health", env: { NEXUSAI_HOME: home, VIRTUAL_ENV: "", NEXUSAI_CHATGPT_ISSUER: "http://127.0.0.1:8766", NEXUSAI_CHATGPT_BASE_URL: "http://127.0.0.1:8766/codex", NEXUSAI_SECRETS_TEST_FILE: join(home, "secrets.json") }, reuseExistingServer: false },
    { command: "npm run dev", url: "http://127.0.0.1:3000/gallery", reuseExistingServer: false, timeout: 120_000 },
  ],
});
