import os from "node:os";
import path from "node:path";

/**
 * Per-user data folder, kept outside the repo (and outside iCloud-synced folders).
 * Matches Electron's app.getPath("userData") for an app named "NexusAI".
 */
export function dataDir(): string {
  if (process.env.NEXUSAI_DATA_DIR) return process.env.NEXUSAI_DATA_DIR;
  if (process.platform === "win32") {
    return path.join(process.env.APPDATA ?? path.join(os.homedir(), "AppData", "Roaming"), "NexusAI");
  }
  if (process.platform === "darwin") return path.join(os.homedir(), "Library", "Application Support", "NexusAI");
  return path.join(os.homedir(), ".config", "NexusAI");
}

export const accountsFile = () => path.join(dataDir(), "mail-accounts.json");
export const rulesFile = () => path.join(dataDir(), "rules.json");
export const databaseFile = () => path.join(dataDir(), "nexusai.db");
