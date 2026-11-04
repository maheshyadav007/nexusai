"use client";

import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { desktopApi } from "@/ui/client/desktop";
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
  const [caption, setCaption] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (desktopApi()?.platform !== "win32") return;
    let timer: ReturnType<typeof setTimeout>;
    const find = () => { const target = document.getElementById("nexus-window-tools"); if (target) setCaption(target); else timer = setTimeout(find, 50); };
    find(); return () => clearTimeout(timer);
  }, []);
  const content = <>
      <ActivityIsland activities={shown} />
      <div className="max-w-popover min-w-0 flex-1">{search}</div>
      <div className="flex items-center gap-1"><ApprovalQueue /><NotificationCenter /></div>
  </>;
  if (caption) return createPortal(content, caption);
  return (
    <header className="flex h-topbar shrink-0 items-center justify-between gap-4 border-b border-line-subtle px-5">
      {content}
    </header>
  );
}
