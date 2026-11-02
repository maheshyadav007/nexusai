"use client";

import type { ReactNode } from "react";
import { t } from "@/ui/strings";
import { useJobs } from "@/ui/client/work";
import { ActivityIsland, type Activity } from "./ActivityIsland";
import { ApprovalQueue } from "./ApprovalQueue";
import { NotificationCenter } from "./NotificationCenter";

const STAGES = 4;

export function TopBar({ activities, search }: { activities?: readonly Activity[]; search?: ReactNode }) {
  const jobs = useJobs();
  const live = (jobs.data?.jobs ?? []).map((job) => ({ id: job.id, title: job.title, detail: job.status, completed: job.progress != null && job.total ? Math.floor((job.progress / job.total) * STAGES) : 1 }));
  const shown = activities ?? live;
  return (
    <header className="flex h-topbar shrink-0 items-center justify-between gap-4 border-b border-line-subtle px-5">
      <ActivityIsland activities={shown} />
      <div className="max-w-popover flex-1">
        {search}
      </div>
      <div className="flex items-center gap-1">
        <ApprovalQueue />
        <NotificationCenter />
      </div>
    </header>
  );
}
