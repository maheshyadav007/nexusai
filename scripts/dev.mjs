// Runs the backend and frontend together, for systems without make, such as Windows.
//   node scripts/dev.mjs          start both
//   node scripts/dev.mjs setup    install what they need first
import { spawn, spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const backend = join(root, "backend");
const frontend = join(root, "frontend");

if (process.argv[2] === "setup") {
  for (const [command, cwd] of [["uv sync", backend], ["npm ci", frontend]]) {
    const done = spawnSync(command, { cwd, shell: true, stdio: "inherit" });
    if (done.status !== 0) process.exit(done.status ?? 1);
  }
  process.exit(0);
}

const running = [
  spawn("uv run nexusai-backend", { cwd: backend, shell: true, stdio: "inherit" }),
  spawn("npm run dev", { cwd: frontend, shell: true, stdio: "inherit" }),
];
const stop = () => {
  for (const child of running) child.kill();
};
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
for (const child of running) child.on("exit", stop);
