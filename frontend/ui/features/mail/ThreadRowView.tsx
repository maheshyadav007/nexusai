"use client";

import Link from "next/link";
import type { ThreadRow } from "@/ui/client/contracts.generated";
import { useShortDate } from "@/ui/client/format";
import { useMailAccounts } from "@/ui/client/mail";
import { useThreadActions } from "@/ui/features/mail/threadActions";
import { Highlight } from "@/ui/features/search/SearchFilters";
import { Icon } from "@/ui/icons";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { t, type StringKey } from "@/ui/strings";

const STATUS_LABELS: Readonly<Record<string, StringKey>> = {
  waiting_on_you: "mail.status.waitingOnYou",
  waiting_on_others: "mail.status.waitingOnOthers",
  resolved: "mail.status.resolved",
  fyi: "mail.status.fyi",
};

export function statusLabel(status: string): string | null {
  const key = STATUS_LABELS[status];
  return key ? t(key) : null;
}

function useOtherPeople(thread: ThreadRow): string {
  const accounts = useMailAccounts();
  const me = accounts.data?.accounts.find((account) => account.name === accounts.data?.active)?.profile.auth.user.toLowerCase();
  const others = thread.participants.filter((person) => person !== me);
  const shown = (others.length ? others : thread.participants).slice(0, 3);
  return shown.join(", ");
}

export function ThreadRowView({ thread, excerpt, href, active = false, highlight }: { thread: ThreadRow; excerpt?: string; href?: string; highlight?: string; active?: boolean }) {
  const others = useOtherPeople(thread);
  const people = thread.sender_name || others;
  const format = useShortDate();
  const unread = thread.unread_count > 0;
  const status = statusLabel(thread.status);
  const actions = useThreadActions(thread, href);
  return (
    <ContextMenu items={actions}>
    <Link href={href ?? `/mail/all/${thread.id}`} aria-current={active ? "page" : undefined} className={`focus-ring flex items-start gap-2 border-b border-line-subtle px-3 py-3 transition-colors duration-fast ${active ? "bg-surface-sunken" : "hover:bg-surface-raised"}`}>
      <span aria-hidden className={`mt-1 h-2 w-2 shrink-0 rounded-full ${unread ? "bg-accent-default" : ""}`} />
      <span className="flex min-w-0 flex-1 flex-col gap-px">
        <span className="flex items-baseline justify-between gap-3">
          <span className={`min-w-0 truncate text-md ${unread ? "font-medium text-ink-primary" : "text-ink-secondary"}`}>
            {people}
            {thread.message_count > 1 ? <span className="ml-1 text-sm tabular-nums text-ink-muted">{thread.message_count}</span> : null}
          </span>
          <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(thread.last_date)}</span>
        </span>
        <span className={`block truncate text-md ${unread ? "text-ink-primary" : "text-ink-secondary"}`}>{thread.subject || t("mail.noSubject")}</span>
        <span className="block truncate text-sm text-ink-muted">{highlight ? <Highlight text={excerpt ?? thread.snippet} words={highlight} /> : (excerpt ?? thread.snippet)}</span>
        {status || thread.category || thread.has_attachments || thread.flagged ? (
          <span className="mt-1 flex items-center gap-2 text-sm text-ink-muted">
            {thread.flagged ? (
              <span role="img" aria-label={t("mail.flagged")} className="text-accent-default">
                <Icon name="flag" className="h-3 w-3" />
              </span>
            ) : null}
            {thread.has_attachments ? (
              <span role="img" aria-label={t("mail.hasAttachments")}>
                <Icon name="attachment" className="h-3 w-3" />
              </span>
            ) : null}
            {thread.category ? <span className="truncate">{thread.category}</span> : null}
            {status && thread.status === "waiting_on_you" ? <span className="shrink-0">{status}</span> : null}
          </span>
        ) : null}
      </span>
    </Link>
    </ContextMenu>
  );
}
