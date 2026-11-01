"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Bell, CheckCircle2, Info, TriangleAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useNexusStore } from "@/lib/store";
import type { ToastNotice } from "@/lib/types";

const toneIcon: Record<ToastNotice["tone"], typeof Info> = {
  info: Info,
  success: CheckCircle2,
  warning: Bell,
  danger: TriangleAlert
};

const toneClass: Record<ToastNotice["tone"], string> = {
  info: "text-status-info",
  success: "text-status-success",
  warning: "text-status-warning",
  danger: "text-status-danger"
};

export function NotificationCenter() {
  const notices = useNexusStore((state) => state.notices);
  const dismissNotice = useNexusStore((state) => state.dismissNotice);

  return (
    <div className="pointer-events-none fixed right-lg top-[calc(var(--layout-topbar)+var(--space-md))] z-50 w-[min(24rem,calc(100vw-var(--space-xl)))] space-y-xs">
      <AnimatePresence initial={false}>
        {notices.slice(0, 4).map((notice) => {
          const Icon = toneIcon[notice.tone];
          return (
            <motion.div
              key={notice.id}
              initial={{ opacity: 0, y: -12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -12, scale: 0.98 }}
              transition={{ duration: 0.25, ease: "easeOut" }}
              className="pointer-events-auto glass-panel rounded-lg p-sm"
            >
              <div className="flex items-start gap-sm">
                <Icon className={`mt-xxs size-md ${toneClass[notice.tone]}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-sm">
                    <p className="truncate text-small text-ink">{notice.title}</p>
                    <span className="shrink-0 text-caption text-ink-tertiary">{notice.time}</span>
                  </div>
                  <p className="mt-xxs text-caption text-ink-subtle">{notice.description}</p>
                </div>
                <Button
                  aria-label="Dismiss notification"
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => dismissNotice(notice.id)}
                >
                  <X className="size-sm" />
                </Button>
              </div>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
