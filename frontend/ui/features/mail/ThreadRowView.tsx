"use client";

import Link from "next/link";
import type { ThreadRow } from "@/ui/client/contracts.generated";
import { useDateTime } from "@/ui/client/format";
import { useMailAccounts } from "@/ui/client/mail";
import { Icon } from "@/ui/icons";
import { Badge } from "@/ui/primitives/Badge";
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

export function ThreadRowView({ thread, excerpt }: { thread: ThreadRow; excerpt?: string }) {
  const people = useOtherPeople(thread);
  const format = useDateTime();
  const unread = thread.unread_count > 0;
  const status = statusLabel(thread.status);
  return (
    <Link href={`/mail/thread/${thread.id}`} className="focus-ring flex items-start gap-3 rounded-md px-3 py-2 transition-colors duration-fast hover:bg-surface-sunken">
      <span aria-hidden className={`mt-2 h-2 w-2 shrink-0 rounded-full ${unread ? "bg-accent-default" : ""}`} />
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-3">
          <span className={`min-w-0 truncate text-md ${unread ? "font-medium text-ink-primary" : "text-ink-secondary"}`}>
            {people}
            {thread.message_count > 1 ? <span className="ml-2 text-sm tabular-nums text-ink-muted">{thread.message_count}</span> : null}
          </span>
          <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(thread.last_date)}</span>
        </span>
        <span className={`block truncate text-md ${unread ? "text-ink-primary" : "text-ink-secondary"}`}>{thread.subject || t("mail.noSubject")}</span>
        <span className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-sm text-ink-muted">{excerpt ?? thread.snippet}</span>
          {thread.has_attachments ? (
            <span role="img" aria-label={t("mail.hasAttachments")} className="text-ink-muted">
              <Icon name="attachment" className="h-3 w-3" />
            </span>
          ) : null}
          {thread.flagged ? (
            <span role="img" aria-label={t("mail.flagged")} className="text-accent-default">
              <Icon name="flag" className="h-3 w-3" />
            </span>
          ) : null}
          {status ? <Badge>{status}</Badge> : null}
          {thread.category ? <Badge>{thread.category}</Badge> : null}
        </span>
      </span>
    </Link>
  );
}
