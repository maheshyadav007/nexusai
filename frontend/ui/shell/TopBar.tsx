"use client";

import { t } from "@/ui/strings";
import { ActivityIsland, type Activity } from "./ActivityIsland";
import { ApprovalQueue } from "./ApprovalQueue";
import { NotificationCenter } from "./NotificationCenter";
import { SearchBox } from "./SearchBox";

export function TopBar({ activities }: { activities?: readonly Activity[] }) {
  return (
    <header className="flex h-topbar shrink-0 items-center justify-between gap-4 border-b border-line-subtle px-5">
      <ActivityIsland {...(activities ? { activities } : {})} />
      <div className="max-w-popover flex-1">
        <SearchBox />
      </div>
      <div className="flex items-center gap-1">
        <ApprovalQueue />
        <NotificationCenter />
      </div>
    </header>
  );
}
