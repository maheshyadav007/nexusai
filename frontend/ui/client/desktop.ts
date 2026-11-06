"use client";

export interface DesktopStatus {
  state: "idle" | "checking" | "available" | "downloading" | "installing" | "ready" | "current" | "error";
  version: string;
  availableVersion: string | null;
  percent: number;
  error: string | null;
  configured: boolean;
}
export interface DesktopApi {
  platform: string;
  caption: (colors: { color: string; symbolColor: string }) => Promise<void>;
  status: () => Promise<DesktopStatus>;
  action: (action: "check" | "download" | "install" | "restart" | "quit" | "logs" | "retry-shutdown") => Promise<DesktopStatus>;
  notify: (notice: { title: string; body?: string; link?: string; silent?: boolean }) => Promise<boolean>;
}
declare global { interface Window { nexusDesktop?: DesktopApi } }
export const desktopApi = () => typeof window === "undefined" ? undefined : window.nexusDesktop;
