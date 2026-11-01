import { execFileSync } from "node:child_process";

export const KEYCHAIN_SERVICE = "NexusAI Mail";

/**
 * Mail passwords never live in config files.
 * Dev (macOS terminal): read from the Keychain. The Electron app will use safeStorage
 * (Keychain on macOS, DPAPI on Windows) behind this same function.
 */
export function getPassword(user: string): string {
  if (process.env.NEXUSAI_MAIL_PASSWORD) return process.env.NEXUSAI_MAIL_PASSWORD;
  if (process.platform === "darwin") {
    try {
      return execFileSync("security", ["find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", user, "-w"], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"]
      }).trim();
    } catch {
      throw new Error(
        `No password in Keychain for ${user}. Add it with:\n` +
          `  security add-generic-password -U -s "${KEYCHAIN_SERVICE}" -a "${user}" -w`
      );
    }
  }
  throw new Error("No password found. Set NEXUSAI_MAIL_PASSWORD for now; the desktop app will store it securely.");
}
