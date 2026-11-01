"use client";

import { useEffect } from "react";
import { useEvents } from "@/ui/client/events";
import { t } from "@/ui/strings";

/** Important mail reaches the person even in another tab, if they've allowed it. */
export function BrowserAlerts() {
  const { subscribe } = useEvents();
  useEffect(
    () =>
      subscribe((event) => {
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
