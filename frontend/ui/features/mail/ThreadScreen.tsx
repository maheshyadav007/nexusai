"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { Draft, MessageView } from "@/ui/client/contracts.generated";
import { useDateTime } from "@/ui/client/format";
import { useCategories, useMoveThread, useReplyDraft, useSetCategory, useSetFlag, useSetRead, useSetStatus, useThread, type ThreadStatus } from "@/ui/client/mail";
import { useSummarize, useThreadRuns, useThreadSummary } from "@/ui/client/work";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { Icon } from "@/ui/icons";
import { Avatar } from "@/ui/primitives/Avatar";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { TextLink } from "@/ui/primitives/TextLink";
import { t, tn } from "@/ui/strings";
import { Composer } from "./Composer";
import { SafeMailFrame } from "./SafeMailFrame";

const STATUSES = [
  { value: "none", label: t("mail.status.none") },
  { value: "waiting_on_you", label: t("mail.status.waitingOnYou") },
  { value: "waiting_on_others", label: t("mail.status.waitingOnOthers") },
  { value: "resolved", label: t("mail.status.resolved") },
  { value: "fyi", label: t("mail.status.fyi") },
];

const sizeOf = (bytes: number) => new Intl.NumberFormat(undefined, { style: "unit", unit: bytes < 1024 ** 2 ? "kilobyte" : "megabyte", maximumFractionDigits: 1 }).format(bytes < 1024 ** 2 ? bytes / 1024 : bytes / 1024 ** 2);

function Attachments({ message }: { message: MessageView }) {
  const [showHidden, setShowHidden] = useState(false);
  const shown = message.attachments.filter((item) => showHidden || item.kind !== "signature");
  return (
    <div className="flex flex-col items-start gap-2">
      {shown.length > 0 ? (
        <ul className="flex flex-wrap gap-2">
          {shown.map((item) => (
            <li key={item.index} className="flex items-center gap-2 rounded-md border border-line-subtle px-3 py-1 text-sm text-ink-secondary">
              <Icon name="attachment" className="h-3 w-3" />
              {item.kind === "risky" ? (
                <span className="text-status-danger">{t("mail.risky", { name: item.filename })}</span>
              ) : (
                <a className="focus-ring rounded-sm underline underline-offset-2" href={`/api/mail/attachment/${message.id}/${item.index}`}>
                  {item.filename}
                </a>
              )}
              <span className="tabular-nums text-ink-muted">{sizeOf(item.size)}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {message.hidden_attachments > 0 ? (
        <Button variant="quiet" className="py-px" onClick={() => setShowHidden((current) => !current)}>
          {t(showHidden ? "mail.hidden.hide" : "mail.hidden.show", { count: message.hidden_attachments })}
        </Button>
      ) : null}
    </div>
  );
}

function Body({ message }: { message: MessageView }) {
  const [showAll, setShowAll] = useState(false);
  if (message.encrypted) return <p className="rounded-md bg-surface-sunken p-3 text-md text-ink-secondary">{t(message.encrypted === "smime" ? "mail.encrypted.smime" : "mail.encrypted.pgp")}</p>;
  if (message.html) return <SafeMailFrame html={message.html} title={message.subject || t("mail.noSubject")} />;
  const hasQuoted = message.text.trim() !== message.own_text.trim();
  return (
    <div className="flex flex-col items-start gap-2">
      <div className="whitespace-pre-wrap break-words text-md text-ink-primary">{showAll ? message.text : message.own_text || message.text}</div>
      {hasQuoted ? (
        <Button variant="quiet" className="py-px" onClick={() => setShowAll((current) => !current)}>
          {t(showAll ? "mail.quotes.hide" : "mail.quotes.show")}
        </Button>
      ) : null}
    </div>
  );
}

function SummaryBlock({ id }: { id: number }) {
  const summary = useThreadSummary(id);
  const summarize = useSummarize();
  const data = summary.data;
  const action =
    !data?.text || data.new_messages ? (
      <Button loading={summarize.isPending} onClick={() => summarize.mutate(id)}>
        {t(data?.text ? "summary.update" : "summary.summarize")}
      </Button>
    ) : null;
  const failure = summarize.isError ? <p role="alert" className="text-sm text-status-danger">{summarize.error instanceof ApiRequestError ? summarize.error.detail.message : t("summary.error")}</p> : null;
  // Until there's something to read, this is only a button beside the others.
  if (!data?.text) {
    return (
      <>
        {action}
        {failure}
      </>
    );
  }
  return (
    <section aria-label={t("summary.title")} className="flex w-full flex-col items-start gap-2 rounded-md bg-surface-sunken p-3">
      <p data-testid="summary-text" className="whitespace-pre-wrap text-md text-ink-primary">{data.text}</p>
      {data.new_messages ? <p className="text-sm text-ink-secondary">{tn("summary.new", data.new_messages)}</p> : null}
      {failure}
      {action}
    </section>
  );
}

function WhyHere({ thread, reason }: { thread: number; reason: string }) {
  const [open, setOpen] = useState(false);
  const runs = useThreadRuns(thread, open);
  const format = useDateTime();
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-ink-muted">
      <span>{t("mail.why", { reason })}</span>
      <Dialog title={t("runs.title")} shape="drawer" open={open} onOpenChange={setOpen} trigger={<Button variant="quiet" className="py-px">{t("runs.open")}</Button>}>
        <ul className="flex flex-col gap-3 overflow-y-auto">
          {(runs.data?.runs ?? []).map((run) => (
            <li key={run.id} data-testid="triage-run" className="flex flex-col gap-1 rounded-md border border-line-subtle p-3 text-md text-ink-secondary">
              <span className="text-sm tabular-nums text-ink-muted">{format(run.time)}</span>
              {run.summary ? <p className="text-ink-primary">{run.summary}</p> : null}
              {run.reason ? <p>{run.reason}</p> : null}
              {run.error ? <p className="text-status-danger">{run.error}</p> : null}
              {(run.facts ?? []).map((fact) => <p key={fact} className="text-sm">{fact}</p>)}
              {run.suggested_action ? <p className="text-sm">{t("runs.action", { action: run.suggested_action })}</p> : null}
            </li>
          ))}
          {runs.isSuccess && !runs.data.runs.length ? <li className="text-md text-ink-muted">{t("runs.none")}</li> : null}
        </ul>
      </Dialog>
    </div>
  );
}

function MessageCard({ message, open: startsOpen, onReply, threadWhy }: { message: MessageView; open: boolean; onReply: (message: MessageView, replyAll: boolean) => void; threadWhy: string | null | undefined }) {
  const [open, setOpen] = useState(startsOpen);
  const format = useDateTime();
  const sender = message.from_name || message.from_addr;
  return (
    <article data-testid="message" className="border-b border-line-subtle last:border-b-0">
      <button type="button" aria-expanded={open} onClick={() => setOpen((current) => !current)} className="focus-ring flex w-full items-center gap-3 rounded-md py-3 text-left">
        <Avatar name={sender} />
        <span className="flex min-w-0 flex-1 flex-col">
          <span className={`truncate text-md ${message.read ? "text-ink-primary" : "font-medium text-ink-primary"}`}>{sender}</span>
          {open ? (
            <span className="truncate text-sm text-ink-muted">
              {t("mail.toLine", { people: [...message.to, ...message.cc].join(", ") })}
              {message.signed ? ` · ${t("mail.signed")}` : ""}
            </span>
          ) : (
            <span className="truncate text-sm text-ink-muted">{message.own_text.slice(0, 120)}</span>
          )}
        </span>
        <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(message.date)}</span>
      </button>
      {open ? (
        <div className="flex flex-col gap-3 pb-4 pl-7">
          {message.added.length > 0 ? <p className="text-sm text-ink-secondary">{t("mail.people.added", { people: message.added.join(", ") })}</p> : null}
          {message.dropped.length > 0 ? <p className="text-sm text-ink-secondary">{t("mail.people.dropped", { people: message.dropped.join(", ") })}</p> : null}
          {message.why && message.why !== threadWhy ? <p className="text-sm text-ink-muted">{t("mail.why", { reason: message.why })}</p> : null}
          <Body message={message} />
          <Attachments message={message} />
          <div className="flex gap-1">
            <Button onClick={() => onReply(message, false)}>
              <Icon name="reply" />
              {t("mail.reply")}
            </Button>
            <Button variant="quiet" onClick={() => onReply(message, true)}>
              <Icon name="replyAll" />
              {t("mail.replyAll")}
            </Button>
          </div>
        </div>
      ) : null}
    </article>
  );
}

const NO_CATEGORY = "none";

export function ThreadScreen({ id }: { id: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const folder = pathname.slice(0, pathname.lastIndexOf("/"));
  const thread = useThread(id);
  const setRead = useSetRead();
  const setFlag = useSetFlag();
  const move = useMoveThread();
  const setStatus = useSetStatus();
  const setCategory = useSetCategory();
  const categories = useCategories();
  const replyDraft = useReplyDraft();
  const [composing, setComposing] = useState<{ draft: Draft; dropped: string[] } | null>(null);

  const unread = thread.data?.thread.unread_count ?? 0;
  const { mutate: markRead } = setRead;
  useEffect(() => {
    if (unread > 0) markRead({ id, read: true });
    // Once on opening: marking unread on purpose mustn't be undone straight away.
  }, [id, thread.isSuccess]);

  if (thread.isPending) return <div aria-busy className="mx-auto flex max-w-reading flex-col gap-3 p-6"><Skeleton className="h-6 w-1/2" /><Skeleton /></div>;
  if (thread.isError) {
    if (thread.error instanceof ApiRequestError && thread.error.detail.code === "thread.not_found") {
      return (
        <div className="mx-auto max-w-reading p-6">
          <h2 className="mb-4 text-xl font-medium text-ink-primary">{t("mail.gone.title")}</h2>
          <EmptyState icon="inbox" title={t("mail.gone.description")} action={<TextLink href={folder}>{t("mail.backToInbox")}</TextLink>} />
        </div>
      );
    }
    return <div className="mx-auto max-w-reading p-6"><ErrorState title={t("mail.thread.error")} onRetry={() => void thread.refetch()} /></div>;
  }
  const { thread: row, messages } = thread.data;
  const reply = (message: MessageView, replyAll: boolean) => replyDraft.mutate({ message_id: message.id, reply_all: replyAll }, { onSuccess: (result) => setComposing({ draft: result.draft, dropped: result.dropped }) });
  const names = (categories.data?.categories ?? []).filter((item) => !item.proposed).map((item) => item.name);
  const categoryOptions = [{ value: NO_CATEGORY, label: t("mail.category.none") }, ...[...new Set([...names, ...(row.category ? [row.category] : [])])].map((name) => ({ value: name, label: name }))];
  const leave = { onSuccess: () => router.push(folder) };
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-4 p-6">
      <header className="flex flex-col gap-3">
        <div className="flex items-center gap-1">
          <TextLink href={folder} className="mr-auto text-sm md:hidden">{t("mail.backToInbox")}</TextLink>
          <IconButton icon="flag" label={t(row.flagged ? "mail.unflag" : "mail.flag")} onClick={() => setFlag.mutate({ id, flagged: !row.flagged })} />
          <IconButton icon="markUnread" label={t("mail.markUnread")} onClick={() => setRead.mutate({ id, read: false })} />
          <IconButton icon="archive" label={t("mail.archive")} onClick={() => move.mutate({ id, to: "archive" }, leave)} />
          <IconButton icon="trash" label={t("mail.delete")} onClick={() => move.mutate({ id, to: "trash" }, leave)} />
        </div>
        <h2 className="break-words text-xl font-medium text-ink-primary">{row.subject || t("mail.noSubject")}</h2>
        <div className="grid gap-2 md:grid-cols-2">
          <Select label={t("mail.status.label")} value={row.status} options={STATUSES} onChange={(status) => setStatus.mutate({ id, status: status as ThreadStatus })} />
          <Select label={t("mail.category")} value={row.category ?? NO_CATEGORY} options={categoryOptions} onChange={(category) => setCategory.mutate({ id, category: category === NO_CATEGORY ? null : category })} />
        </div>
        {row.why ? <WhyHere thread={id} reason={row.why} /> : null}
        <div className="flex flex-wrap items-center gap-2">
          <AskAgent context={[`thread:${id}`]} title={row.subject || t("mail.noSubject")} />
          <SummaryBlock id={id} />
        </div>
      </header>
      <div className="flex flex-col">
        {messages.map((message, index) => (
          <MessageCard threadWhy={row.why} key={message.id} message={message} open={index === messages.length - 1} onReply={reply} />
        ))}
      </div>
      {composing ? (
        <section className="rounded-lg border border-line-subtle bg-surface-raised p-4">
          <Composer initial={composing.draft} dropped={composing.dropped} onDone={() => setComposing(null)} />
        </section>
      ) : null}
    </div>
  );
}
