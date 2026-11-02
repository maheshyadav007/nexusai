"use client";

import Link from "next/link";
import { Popover } from "@/ui/primitives/Popover";
import { Pressable } from "@/ui/primitives/Pressable";
import { StageBar } from "@/ui/primitives/StageBar";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { TextLink } from "@/ui/primitives/TextLink";
import { t } from "@/ui/strings";

export interface Activity {
  id: string;
  title: string;
  detail: string;
  completed: number;
}

/** The v9 status chip. Quiet when idle; only running work gets the strong surface. */
export function ActivityIsland({ activities = [] }: { activities?: readonly Activity[] }) {
  const [first] = activities;
  if (!first) {
    return (
      <Link href="/cockpit" data-testid="activity-idle" className="focus-ring flex items-center gap-2 rounded-sm text-md text-ink-muted transition-colors duration-fast hover:text-ink-primary">
        <StatusDot tone="done" />
        {t("activity.idle")}
      </Link>
    );
  }
  return (
    <Popover
      label={t("activity.title")}
      trigger={
        <Pressable className="flex min-w-0 items-center gap-3 rounded-full bg-surface-inverse px-4 py-1 text-md text-ink-inverse transition-opacity duration-fast hover:opacity-90">
          <StatusDot tone="running" />
          <span className="truncate">{first.title}</span>
          <span className="shrink-0 text-sm tabular-nums">{activities.length}</span>
        </Pressable>
      }
    >
      <h2 className="mb-3 text-md font-medium">{t("activity.title")}</h2>
      <ul className="flex flex-col gap-3">
        {activities.map((activity) => (
          <li key={activity.id} className="flex flex-col gap-1">
            <div className="flex items-center justify-between gap-3">
              <span className="min-w-0 truncate text-md">{activity.title}</span>
              <StageBar label={activity.detail} completed={activity.completed} />
            </div>
            <p className="text-sm text-ink-muted">{activity.detail}</p>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-sm">
        <TextLink href="/cockpit">{t("activity.open")}</TextLink>
      </p>
    </Popover>
  );
}
