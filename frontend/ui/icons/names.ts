import type { ComponentType } from "react";

// Features name an icon by what it's for. Every icon set in ./sets draws each of these, and
// TypeScript refuses a set that misses one, so a set can be swapped in whole.
export const ICON_NAMES = [
  "eye", "eyeOff", "activity", "lockedChat", "pin", "unpin", "repeat", "more", "thinking", "copy",
  "skipped", "connectors", "cockpit", "compact", "like", "dislike", "retry", "previous", "edit",
  "stop", "minimize", "openFull", "newChat", "chat", "followUp", "file", "priority", "important",
  "starred", "reply", "replyAll", "forward", "trash", "add", "markUnread", "folder",
  // The two kinds of folder a person or the AI makes: filed by rules, or sorted by the AI.
  "folderRule", "folderSmart",
  // A label on the server, such as a Gmail label: mail the person tagged, not a folder the app files into.
  "label",
  // What the AI skips: the section, mail tools send, and invitations.
  "keptFromAi", "automated", "calendar", "moreFolders", "allMail",
  "agent", "all", "approvals", "archive", "attachment", "categories", "channel", "check",
  "chevronDown", "soundOn", "soundOff", "chevronLeft", "info", "chevronRight", "close", "collapse",
  "customize", "documents", "drafts", "error", "expand", "flag", "fromEmail", "grip", "inbox",
  "loading", "logs", "memory", "moveDown", "moveUp", "notifications", "offline", "panels",
  "reminders", "schedules", "date", "time", "search", "sent", "sessions", "settings", "tasks",
  "background", "today", "uploaded",
] as const;

export type IconName = (typeof ICON_NAMES)[number];

export type Glyph = ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

export type IconSet = Readonly<Record<IconName, Glyph>>;
