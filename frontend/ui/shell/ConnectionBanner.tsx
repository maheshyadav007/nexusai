"use client";

import { useEvents } from "@/ui/client/events";
import { t } from "@/ui/strings";

export function ConnectionBanner() {
  const { connected } = useEvents();
  if (connected) return null;
  return (
    <div role="status" className="fixed inset-x-0 top-0 z-50 bg-surface-inverse px-4 py-2 text-center text-sm text-ink-inverse">
      {t("connection.reconnecting")}
    </div>
  );
}
