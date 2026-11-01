"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useMailAccounts, useMailStatus, useThreads, type FolderRole } from "@/ui/client/mail";
import type { IconName } from "@/ui/icons";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { OfflineNotice } from "@/ui/primitives/OfflineNotice";
import { Segmented } from "@/ui/primitives/Segmented";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { TextLink } from "@/ui/primitives/TextLink";
import { t, type StringKey } from "@/ui/strings";
import { ThreadRowView } from "./ThreadRowView";

const ALL = "all";
const ROW_ESTIMATE = 72;

export function SyncNotice() {
  const status = useMailStatus();
  const state = status.data?.state;
  if (state === "offline" || state === "failed") {
    return <OfflineNotice message={status.data?.message ?? t("mail.sync.offline")} />;
  }
  if (state === "connecting" || state === "syncing" || state === "backfilling") {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-ink-muted">
        <StatusDot tone="running" />
        {t(state === "backfilling" ? "mail.sync.backfilling" : "mail.sync.syncing")}
      </p>
    );
  }
  return null;
}

export function NoAccount() {
  return <EmptyState icon="inbox" title={t("mail.noAccount.title")} description={t("mail.noAccount.description")} action={<TextLink href="/settings?section=accounts">{t("mail.noAccount.action")}</TextLink>} />;
}

export function MailList({ title, folder, emptyIcon, emptyTitle, actions, showCategories = true }: { title: string; folder: FolderRole; emptyIcon: IconName; emptyTitle: StringKey; actions?: ReactNode; showCategories?: boolean }) {
  const accounts = useMailAccounts();
  const [category, setCategory] = useState(ALL);
  const threads = useThreads(folder, category === ALL ? null : category);
  const scroller = useRef<HTMLDivElement>(null);
  const rows = threads.data?.pages.flatMap((page) => page.threads) ?? [];
  const categories = threads.data?.pages[0]?.categories ?? [];
  const virtual = useVirtualizer({ count: rows.length, getScrollElement: () => scroller.current, estimateSize: () => ROW_ESTIMATE, overscan: 10 });
  const items = virtual.getVirtualItems();
  const last = items[items.length - 1];

  const { hasNextPage, isFetchingNextPage, fetchNextPage } = threads;
  useEffect(() => {
    if (last && last.index >= rows.length - 1 && hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [last, rows.length, hasNextPage, isFetchingNextPage, fetchNextPage]);

  if (accounts.data && !accounts.data.active) {
    return (
      <div className="mx-auto max-w-content p-6">
        <h1 className="mb-4 font-serif text-display text-ink-primary">{title}</h1>
        <NoAccount />
      </div>
    );
  }
  // Virtual rows are placed by live measurements, which only a style can carry.
  const total = { height: virtual.getTotalSize() };
  return (
    <div className="flex h-full flex-col gap-3 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-serif text-display text-ink-primary">{title}</h1>
        <div className="flex items-center gap-3">
          <SyncNotice />
          {actions}
        </div>
      </header>
      {showCategories && categories.length > 0 ? <Segmented label={t("mail.category")} value={category} options={[{ value: ALL, label: t("mail.category.all") }, ...categories.map((value) => ({ value, label: value }))]} onChange={setCategory} /> : null}
      {threads.isPending ? (
        <div aria-busy className="flex flex-col gap-3">
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-full" />
        </div>
      ) : null}
      {threads.isError ? <ErrorState title={t("mail.list.error")} onRetry={() => void threads.refetch()} /> : null}
      {threads.isSuccess && rows.length === 0 ? <EmptyState icon={emptyIcon} title={t(emptyTitle)} /> : null}
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
        <ul aria-label={title} {...{ style: total }} className="relative w-full">
          {items.map((item) => {
            const thread = rows[item.index];
            if (!thread) return null;
            const place = { transform: `translateY(${item.start}px)` };
            return (
              <li key={thread.id} data-index={item.index} ref={virtual.measureElement} {...{ style: place }} data-testid="thread-row" className="absolute left-0 top-0 w-full">
                <ThreadRowView thread={thread} />
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
