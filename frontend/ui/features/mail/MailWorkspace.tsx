"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { useParams, usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useGetMoreFromFolder, useMailAccounts, useMailFolders, useSearch, useThreads, type FolderRole } from "@/ui/client/mail";
import type { IconName } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Input } from "@/ui/primitives/Input";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t, type StringKey } from "@/ui/strings";
import { Composer } from "./Composer";
import { NoAccount, SyncNotice } from "./MailList";
import { ThreadRowView } from "./ThreadRowView";

const ROW_ESTIMATE = 72;

const FOLDERS: Readonly<Record<string, { title: StringKey; icon: IconName; empty: StringKey; role: FolderRole }>> = {
  priority: { title: "nav.priority", icon: "priority", empty: "mail.empty.priority", role: "priority" },
  all: { title: "nav.allMail", icon: "inbox", empty: "mail.empty.inbox", role: "all" },
  sent: { title: "nav.sent", icon: "sent", empty: "mail.empty.sent", role: "sent" },
  archive: { title: "nav.archive", icon: "archive", empty: "mail.empty.archive", role: "archive" },
  trash: { title: "nav.trash", icon: "trash", empty: "mail.empty.trash", role: "trash" },
};

export function NewMessage() {
  const [open, setOpen] = useState(false);
  return (
    <Dialog title={t("mail.compose")} shape="drawer" open={open} onOpenChange={setOpen} trigger={<Button variant="primary">{t("mail.new")}</Button>}>
      <Composer initial={{}} onDone={() => setOpen(false)} />
    </Dialog>
  );
}

export function NothingOpen() {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <p className="text-md text-ink-muted">{t("mail.nothingOpen")}</p>
    </div>
  );
}

/** A quick search inside the folder on screen, in place of its list. */
function FilteredList({ text, role, category, location, base, title }: { text: string; role: FolderRole; category: string | null; location: string | null; base: string; title: string }) {
  const pathname = usePathname();
  const search = useSearch({ query: text, ...(category ? { category } : {}), ...(location ? { location } : role === "all" || role === "priority" ? {} : { folder: role }) }, true);
  const hits = search.data?.hits ?? [];
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      {search.isPending ? <div className="p-3"><Skeleton className="h-6 w-full" /></div> : null}
      {search.isSuccess && !hits.length ? <div className="p-3"><EmptyState icon="search" title={t("search.none")} /></div> : null}
      <ul aria-label={title}>
        {hits.map((hit) => (
          <li key={hit.thread.id} data-testid="thread-row" className="border-b border-line-subtle">
            <ThreadRowView thread={hit.thread} excerpt={hit.excerpt} highlight={text} href={`${base}/${hit.thread.id}`} active={pathname === `${base}/${hit.thread.id}`} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function ThreadList({ title, role, category, location, base, icon, empty }: { title: string; role: FolderRole; category: string | null; location: string | null; base: string; icon: IconName; empty: StringKey }) {
  const threads = useThreads(role, category, location);
  const scroller = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const rows = threads.data?.pages.flatMap((page) => page.threads) ?? [];
  const virtual = useVirtualizer({ count: rows.length, getScrollElement: () => scroller.current, estimateSize: () => ROW_ESTIMATE, overscan: 10 });
  const items = virtual.getVirtualItems();
  const last = items[items.length - 1];
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = threads;
  useEffect(() => {
    if (last && last.index >= rows.length - 1 && hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [last, rows.length, hasNextPage, isFetchingNextPage, fetchNextPage]);
  // Virtual rows are placed by live measurements, which only a style can carry.
  const total = { height: virtual.getTotalSize() };
  return (
    <>
      {threads.isPending ? (
        <div aria-busy className="flex flex-col gap-3 p-3">
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-full" />
        </div>
      ) : null}
      {threads.isError ? <div className="p-3"><ErrorState title={t("mail.list.error")} onRetry={() => void threads.refetch()} /></div> : null}
      {threads.isSuccess && rows.length === 0 ? <div className="p-3"><EmptyState icon={icon} title={t(empty)} /></div> : null}
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
        <ul aria-label={title} {...{ style: total }} className="relative w-full">
          {items.map((item) => {
            const thread = rows[item.index];
            if (!thread) return null;
            const href = `${base}/${thread.id}`;
            const place = { transform: `translateY(${item.start}px)` };
            return (
              <li key={thread.id} data-index={item.index} ref={virtual.measureElement} {...{ style: place }} data-testid="thread-row" className="absolute left-0 top-0 w-full">
                <ThreadRowView thread={thread} href={href} active={pathname === href} />
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}

/** A folder or a category: its conversations on the left, the open one on the right. */
/** A folder on the server that's only partly here says so, and can fetch the rest. */
function FolderProgress({ name }: { name: string }) {
  const folders = useMailFolders();
  const more = useGetMoreFromFolder();
  const row = folders.data?.folders.find((item) => item.name === name);
  const left = (row?.on_server ?? 0) - (row?.here ?? 0);
  if (!row || left <= 0) return null;
  return (
    <div data-testid="folder-progress" className="flex flex-wrap items-center justify-between gap-2 border-b border-line-subtle px-4 py-2 text-sm text-ink-secondary">
      <span className="tabular-nums">{t("mail.folder.here", { here: (row.here ?? 0).toLocaleString(), total: (row.on_server ?? 0).toLocaleString() })}</span>
      <Button variant="quiet" className="py-px" loading={more.isPending} onClick={() => more.mutate({ folder: name })}>{t("mail.folder.getRest")}</Button>
    </div>
  );
}

export function MailWorkspace({ folder, category = null, location = null, children }: { folder: string; category?: string | null; location?: string | null; children: ReactNode }) {
  const accounts = useMailAccounts();
  const params = useParams();
  const shown = FOLDERS[folder] ?? (FOLDERS.all as NonNullable<(typeof FOLDERS)[string]>);
  const title = category ?? location?.split("/").pop() ?? t(shown.title);
  const base = location ? `/mail/folder/${encodeURIComponent(location)}` : category ? `/mail/category/${encodeURIComponent(category)}` : `/mail/${folder}`;
  const reading = Boolean(params.thread);
  const [filter, setFilter] = useState("");
  if (accounts.data && !accounts.data.active) {
    return (
      <div className="mx-auto max-w-content p-6">
        <h1 className="mb-4 text-xl font-medium text-ink-primary">{title}</h1>
        <NoAccount />
      </div>
    );
  }
  return (
    <div className="flex h-full">
      <section aria-label={title} className={`min-h-0 w-full shrink-0 flex-col border-r border-line-subtle md:flex md:w-mail-list ${reading ? "hidden" : "flex"}`}>
        <header className="flex h-topbar shrink-0 items-center justify-between gap-3 border-b border-line-subtle px-4">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-medium text-ink-primary">{title}</h1>
            <SyncNotice />
          </div>
          <NewMessage />
        </header>
        {location ? <FolderProgress name={location} /> : null}
        <div className="shrink-0 border-b border-line-subtle p-2">
          <Input type="search" aria-label={t("mail.filter")} placeholder={t("mail.filter")} value={filter} onChange={(event) => setFilter(event.target.value)} />
        </div>
        {filter.trim() ? (
          <FilteredList text={filter.trim()} role={shown.role} category={category} location={location} base={base} title={title} />
        ) : (
          <ThreadList title={title} role={shown.role} category={category} location={location} base={base} icon={shown.icon} empty={category || location ? "mail.empty.category" : shown.empty} />
        )}
      </section>
      <div className={`min-h-0 min-w-0 flex-1 overflow-y-auto ${reading ? "" : "hidden md:block"}`}>{children}</div>
    </div>
  );
}
