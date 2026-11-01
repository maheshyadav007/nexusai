"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useDateTime } from "@/ui/client/format";
import { useMarkRead, useNotifications } from "@/ui/client/notifications";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Popover } from "@/ui/primitives/Popover";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { t } from "@/ui/strings";

const ALL = "all";

export function NotificationCenter() {
  const router = useRouter();
  const [kind, setKind] = useState(ALL);
  const list = useNotifications(kind === ALL ? null : kind);
  const markRead = useMarkRead();
  const format = useDateTime();
  const unread = list.data?.unread ?? 0;
  const items = list.data?.items ?? [];
  const label = unread ? t("notifications.unread", { count: unread }) : t("notifications.title");
  return (
    <Popover
      label={t("notifications.title")}
      trigger={
        <button type="button" aria-label={label} className="focus-ring inline-flex items-center gap-1 rounded-md p-2 text-ink-secondary transition-colors duration-fast hover:bg-surface-sunken hover:text-ink-primary">
          <Icon name="notifications" />
          {unread ? <span className="text-sm tabular-nums text-accent-default">{unread}</span> : null}
        </button>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-md font-medium">{t("notifications.title")}</h2>
          {unread ? (
            <Button variant="quiet" onClick={() => markRead.mutate(null)}>
              {t("notifications.markAll")}
            </Button>
          ) : null}
        </div>
        {(list.data?.kinds.length ?? 0) > 1 ? (
          <Select value={kind} options={[{ value: ALL, label: t("notifications.all") }, ...(list.data?.kinds ?? []).map((value) => ({ value, label: value }))]} onChange={setKind} />
        ) : null}
        {list.isPending ? <Skeleton /> : null}
        {list.isError ? <ErrorState title={t("notifications.error")} onRetry={() => void list.refetch()} /> : null}
        {list.isSuccess && items.length === 0 ? <EmptyState icon="notifications" title={t("notifications.empty.title")} description={t("notifications.empty.description")} /> : null}
        <ul className="flex max-h-popover flex-col gap-1 overflow-y-auto">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className="focus-ring flex w-full items-start gap-2 rounded-sm p-2 text-left transition-colors duration-fast hover:bg-surface-sunken"
                onClick={() => {
                  if (!item.read) markRead.mutate(item.id);
                  if (item.link) router.push(item.link);
                }}
              >
                <span className="pt-1">{item.read ? <StatusDot tone="idle" /> : <StatusDot tone="running" />}</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-md text-ink-primary">{item.title}</span>
                  {item.detail ? <span className="block text-sm text-ink-muted">{item.detail}</span> : null}
                  <span className="block text-sm tabular-nums text-ink-muted">{format(item.time)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </Popover>
  );
}
