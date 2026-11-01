"use client";

import { EmptyState } from "@/ui/primitives/EmptyState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Popover } from "@/ui/primitives/Popover";
import { t } from "@/ui/strings";
import { ActivityIsland, type Activity } from "./ActivityIsland";
import { NotificationCenter } from "./NotificationCenter";

export function TopBar({ activities }: { activities?: readonly Activity[] }) {
  return (
    <header className="flex h-topbar shrink-0 items-center justify-between gap-4 border-b border-line-subtle px-5">
      <ActivityIsland {...(activities ? { activities } : {})} />
      <div className="flex items-center gap-1">
        <Popover label={t("approvals.title")} trigger={<IconButton icon="approvals" label={t("approvals.title")} />}>
          <EmptyState icon="approvals" title={t("approvals.empty.title")} description={t("approvals.empty.description")} />
        </Popover>
        <NotificationCenter />
      </div>
    </header>
  );
}
