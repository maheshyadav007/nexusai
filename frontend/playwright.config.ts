import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

const home = mkdtempSync(join(tmpdir(), "nexusai-e2e-"));

export default defineConfig({
  testDir: "e2e",
  use: { baseURL: "http://127.0.0.1:3000" },
  webServer: [
    { command: "uv run --quiet nexusai-backend", cwd: "../backend", url: "http://127.0.0.1:8765/api/health", env: { NEXUSAI_HOME: home, VIRTUAL_ENV: "" }, reuseExistingServer: false },
    { command: "npm run dev -- --hostname 127.0.0.1 --port 3000", url: "http://127.0.0.1:3000/gallery", reuseExistingServer: false, timeout: 120_000 },
  ],
});
