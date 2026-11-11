"use client";

export interface DesktopStatus {
  state: "idle" | "checking" | "available" | "downloading" | "installing" | "ready" | "current" | "error";
  version: string;
  availableVersion: string | null;
  percent: number;
  error: string | null;
  configured: boolean;
}
/** The quick-ask box: its shortcut, and whether it can read what's selected in other apps. */
export interface QuickAskStatus {
  shortcut: string;
  enabled: boolean;
  selection: boolean;
  /** Whether the shortcut is held right now; another app may have it. */
  registered: boolean;
  /** On a Mac, reading the selection needs Accessibility. */
  selectionAllowed: boolean;
  platform: string;
  /** Whether the box is on screen. */
  visible: boolean;
  error?: "taken" | "invalid";
}
export interface QuickAskChange { shortcut?: string; enabled?: boolean; selection?: boolean }
export interface QuickAskApi {
  (action: "status" | "allow-selection" | "open"): Promise<QuickAskStatus>;
  (action: "update", value: QuickAskChange): Promise<QuickAskStatus>;
  (action: "resize", value: number): Promise<null>;
  (action: "hide"): Promise<null>;
  /** The shortcut's last press, if the page hasn't had it yet. */
  (action: "take"): Promise<{ selection: string; shortcut: string } | null>;
  (action: "open-in-app", value: string): Promise<null>;
}
export interface DesktopApi {
  platform: string;
  caption: (colors: { color: string; symbolColor: string }) => Promise<void>;
  status: () => Promise<DesktopStatus>;
  action: (action: "check" | "download" | "install" | "restart" | "quit" | "logs" | "retry-shutdown") => Promise<DesktopStatus>;
  notify: (notice: { title: string; body?: string; link?: string; silent?: boolean }) => Promise<boolean>;
  quick?: QuickAskApi;
  onQuickOpen?: (listener: (detail: { selection: string; shortcut: string }) => void) => () => void;
}
declare global { interface Window { nexusDesktop?: DesktopApi } }
export const desktopApi = () => typeof window === "undefined" ? undefined : window.nexusDesktop;
