import fs from "node:fs";
import { accountsFile } from "./paths";
import type { MailAccountsConfig, MailProfile } from "./types";

export function loadAccounts(file = accountsFile()): MailAccountsConfig {
  if (!fs.existsSync(file)) {
    throw new Error(`No mail config at ${file}. Run "npm run mail -- init <email>" to create one.`);
  }
  const config = JSON.parse(fs.readFileSync(file, "utf8")) as MailAccountsConfig;
  if (!config.profiles?.[config.activeProfile]) {
    throw new Error(`activeProfile "${config.activeProfile}" is not defined in ${file}`);
  }
  return config;
}

export function activeProfile(config = loadAccounts()): { name: string; profile: MailProfile } {
  return { name: config.activeProfile, profile: config.profiles[config.activeProfile] };
}

/** Starter config with a Gmail test profile and a corporate profile to fill in. */
export function templateAccounts(gmailUser: string): MailAccountsConfig {
  return {
    activeProfile: "gmail-test",
    profiles: {
      "gmail-test": {
        label: "Gmail (test)",
        imap: { host: "imap.gmail.com", port: 993, secure: true },
        smtp: { host: "smtp.gmail.com", port: 465, secure: true },
        auth: { type: "password", user: gmailUser },
        mailboxes: ["INBOX"]
      },
      corp: {
        label: "Work",
        imap: { host: "imap.example.corp", port: 993, secure: true },
        smtp: { host: "smtp.example.corp", port: 587, secure: false, starttls: true },
        auth: { type: "password", user: "you@example.corp" },
        mailboxes: ["INBOX"]
      }
    }
  };
}
