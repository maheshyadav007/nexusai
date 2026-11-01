"use client";

import { useState } from "react";
import type { Draft } from "@/ui/client/contracts.generated";
import { useDrafts } from "@/ui/client/mail";
import { Badge } from "@/ui/primitives/Badge";
import { Dialog } from "@/ui/primitives/Dialog";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";
import { Composer } from "./Composer";
import { NewMessage } from "./InboxScreen";
import { NoAccount, SyncNotice } from "./MailList";
import { useMailAccounts } from "@/ui/client/mail";

export function DraftsScreen() {
  const accounts = useMailAccounts();
  const drafts = useDrafts();
  const [editing, setEditing] = useState<Draft | null>(null);
  const items = drafts.data?.drafts ?? [];
  return (
    <div className="mx-auto flex max-w-content flex-col gap-4 p-6">
      <header className="flex items-center justify-between gap-3">
        <h1 className="font-serif text-display text-ink-primary">{t("nav.drafts")}</h1>
        <div className="flex items-center gap-3">
          <SyncNotice />
          <NewMessage />
        </div>
      </header>
      {accounts.data && !accounts.data.active ? <NoAccount /> : null}
      {drafts.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {drafts.isError ? <ErrorState title={t("mail.list.error")} onRetry={() => void drafts.refetch()} /> : null}
      {drafts.isSuccess && items.length === 0 && accounts.data?.active ? <EmptyState icon="drafts" title={t("mail.empty.drafts")} /> : null}
      <ul className="flex flex-col gap-1">
        {items.map((draft) => (
          <li key={draft.id}>
            <button type="button" data-testid="draft-row" onClick={() => setEditing(draft)} className="focus-ring flex w-full items-baseline gap-3 rounded-md px-3 py-2 text-left transition-colors duration-fast hover:bg-surface-sunken">
              <span className="min-w-0 flex-1 truncate text-md text-ink-primary">{draft.subject || t("mail.noSubject")}</span>
              <span className="min-w-0 truncate text-sm text-ink-muted">{(draft.to ?? []).map((person) => person.address).join(", ")}</span>
              {draft.source === "agent" ? <Badge tone="accent">{t("mail.draft.agent")}</Badge> : null}
            </button>
          </li>
        ))}
      </ul>
      <Dialog title={t("mail.compose")} shape="drawer" open={Boolean(editing)} onOpenChange={(open) => (open ? null : setEditing(null))}>
        {editing ? <Composer initial={editing} onDone={() => setEditing(null)} /> : null}
      </Dialog>
    </div>
  );
}
