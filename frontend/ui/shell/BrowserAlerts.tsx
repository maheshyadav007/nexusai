"use client";

import { useEffect, useRef } from "react";
import { useEvents } from "@/ui/client/events";
import { useSettings } from "@/ui/client/settings";
import { playChime } from "@/ui/client/sound";
import { useQuietHours } from "@/ui/client/work";
import { t } from "@/ui/strings";

const MAIL_AGENT = "mail-agent";

/** Which kind of notice an event is, for the person to mute or not. Most events aren't one. */
function kindOf(event: { type: string; payload: Record<string, unknown> }): string | null {
  if (event.type === "notification.requested") {
    if (event.payload.kind === "urgent-mail") return "urgent-mail";
    if (event.payload.kind === "reminder") return "reminder";
    return "needs-you";
  }
  if (event.type === "approval.changed" && event.payload.status === "pending") return "needs-you";
  if (event.type === "channel.posted" && event.payload.kind === "ask") return "needs-you";
  // The Mail agent finishes every email, so only chats a person is waiting on make a sound.
  if (event.type === "session.changed" && event.payload.status === "done" && event.payload.id !== MAIL_AGENT) return "agent-finished";
  return null;
}

const toMinutes = (time: string) => {
  const [hours, minutes] = time.split(":").map(Number);
  return (hours ?? 0) * 60 + (minutes ?? 0);
};

function isQuiet(start: string, end: string, now: Date): boolean {
  const at = now.getHours() * 60 + now.getMinutes();
  const from = toMinutes(start);
  const to = toMinutes(end);
  return from <= to ? at >= from && at < to : at >= from || at < to;
}

/** Important mail reaches the person in another tab if they've allowed it, and a sound here. */
export function BrowserAlerts() {
  const { subscribe } = useEvents();
  const settings = useSettings();
  const quiet = useQuietHours();
  const latest = useRef({ muted: false, off: [] as readonly string[], quiet: quiet.data });
  latest.current = { muted: settings.data?.sound_muted ?? false, off: settings.data?.sound_off ?? [], quiet: quiet.data };
  useEffect(
    () =>
      subscribe((event) => {
        const kind = kindOf(event);
        const now = latest.current;
        const hushed = now.quiet?.enabled && isQuiet(now.quiet.start ?? "", now.quiet.end ?? "", new Date());
        if (kind && !now.muted && !hushed && !now.off.includes(kind)) playChime();
        if (event.type !== "notification.requested" || event.payload.kind !== "urgent-mail") return;
        if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
        const alert = new Notification(String(event.payload.title ?? t("app.name")), { body: String(event.payload.detail ?? "") });
        const link = event.payload.link;
        alert.onclick = () => {
          window.focus();
          if (typeof link === "string") window.location.assign(link);
        };
      }),
    [subscribe],
  );
  return null;
}
