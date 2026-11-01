"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { ChannelMessage, TodayThread } from "@/ui/client/contracts.generated";
import { useDateTime } from "@/ui/client/format";
import { useMailStatus } from "@/ui/client/mail";
import { leaveFirstMessage, useApprovals, useCreateSession } from "@/ui/client/sessions";
import { useChannel, useDismissChannel, useRespondChannel, useToday } from "@/ui/client/work";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { TextLink } from "@/ui/primitives/TextLink";
import { ApprovalDetails } from "@/ui/shell/ApprovalQueue";
import { t, tn, type StringKey } from "@/ui/strings";

const KIND_LABELS: Readonly<Record<string, StringKey>> = { ask: "channel.ask", suggest: "channel.suggest", tell: "channel.tell" };

function ThreadList({ title, threads, empty }: { title: string; threads: readonly TodayThread[]; empty: string }) {
  const format = useDateTime();
  return (
    <Card title={title}>
      {threads.length === 0 ? <p className="text-md text-ink-muted">{empty}</p> : null}
      <ul className="flex flex-col gap-px">
        {threads.map((thread) => (
          <li key={thread.id}>
            <Link href={`/mail/thread/${thread.id}`} data-testid="today-thread" className="focus-ring flex flex-col gap-1 rounded-md p-2 transition-colors duration-fast hover:bg-surface-sunken">
              <span className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate text-md text-ink-primary">{thread.subject || t("mail.noSubject")}</span>
                <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(thread.last_date)}</span>
              </span>
              {thread.why ? <span className="truncate text-sm text-ink-muted">{thread.why}</span> : null}
              {thread.importance === "high" ? <span><Badge tone="accent">{t("today.important")}</Badge></span> : null}
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function ChannelCard({ message }: { message: ChannelMessage }) {
  const respond = useRespondChannel();
  const dismiss = useDismissChannel();
  const [answer, setAnswer] = useState("");
  const options = message.options ?? [];
  const label = KIND_LABELS[message.kind];
  return (
    <li data-testid="channel-message" className="flex flex-col gap-2 rounded-md border border-line-subtle p-3">
      <p className="flex items-center gap-2 text-sm text-ink-muted">
        {label ? t(label) : message.kind} · {message.agent}
        {message.count > 1 ? <Badge>{t("channel.times", { count: message.count })}</Badge> : null}
      </p>
      <p className="break-words text-md text-ink-primary">{message.text}</p>
      {message.kind === "ask" ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (answer.trim()) respond.mutate({ id: message.id, answer: answer.trim() });
          }}
        >
          {options.map((option) => (
            <Button key={option} onClick={() => respond.mutate({ id: message.id, answer: option })}>
              {option}
            </Button>
          ))}
          <div className="min-w-0 flex-1">
            <Input aria-label={t("channel.reply")} placeholder={t("channel.reply")} value={answer} onChange={(event) => setAnswer(event.target.value)} />
          </div>
          <Button type="submit" variant="primary" loading={respond.isPending} disabled={!answer.trim()}>
            {t("channel.answer")}
          </Button>
        </form>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        {message.session ? <TextLink className="text-sm" href={`/agent/sessions/${message.session}`}>{t("channel.openSession")}</TextLink> : null}
        {message.thread ? <TextLink className="text-sm" href={`/mail/thread/${message.thread}`}>{t("channel.openSource")}</TextLink> : null}
        <Button variant="quiet" className="py-px" onClick={() => dismiss.mutate(message.id)}>
          {t(message.kind === "ask" ? "channel.skip" : "channel.dismiss")}
        </Button>
      </div>
    </li>
  );
}

function UserChannel() {
  const channel = useChannel();
  const approvals = useApprovals();
  const messages = channel.data?.messages ?? [];
  const pending = approvals.data?.approvals ?? [];
  return (
    <Card title={t("channel.title")} description={t("channel.description")}>
      {channel.isPending ? <Skeleton /> : null}
      {channel.isError ? <ErrorState title={t("channel.error")} onRetry={() => void channel.refetch()} /> : null}
      {channel.isSuccess && messages.length === 0 && pending.length === 0 ? <p className="text-md text-ink-muted">{t("channel.empty")}</p> : null}
      <ul className="flex flex-col gap-3">
        {pending.map((approval) => (
          <li key={approval.id} className="rounded-md border border-line-strong p-3">
            <ApprovalDetails approval={approval} />
          </li>
        ))}
        {messages.map((message) => (
          <ChannelCard key={message.id} message={message} />
        ))}
      </ul>
    </Card>
  );
}

function PromptBar() {
  const router = useRouter();
  const create = useCreateSession();
  const [text, setText] = useState("");
  return (
    <form
      className="flex items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (!text.trim()) return;
        create.mutate(
          { title: text.trim().slice(0, 60) },
          {
            onSuccess: (session) => {
              leaveFirstMessage(session.id, text.trim());
              router.push(`/agent/sessions/${session.id}`);
            },
          },
        );
      }}
    >
      <div className="min-w-0 flex-1">
        <Textarea aria-label={t("today.ask")} placeholder={t("today.ask")} rows={1} value={text} onChange={(event) => setText(event.target.value)} />
      </div>
      <Button type="submit" variant="primary" loading={create.isPending} disabled={!text.trim()}>
        {t("sessions.send")}
      </Button>
    </form>
  );
}

export function TodayScreen() {
  const today = useToday();
  const mail = useMailStatus();
  const noMail = mail.data?.state === "off" && !today.data?.needs_you.length && !today.data?.waiting.length;
  return (
    <div className="mx-auto flex max-w-content flex-col gap-5 p-6">
      <header>
        <h1 className="font-serif text-display text-ink-primary">{t("nav.today")}</h1>
        {today.data ? <p data-testid="today-brief" className="mt-1 text-md tabular-nums text-ink-secondary">{today.data.brief}</p> : null}
      </header>
      <PromptBar />
      {today.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {today.isError ? <ErrorState title={t("today.error")} onRetry={() => void today.refetch()} /> : null}
      {today.data?.prep_text ? (
        <Card title={t("today.prep")}>
          <p data-testid="today-prep" className="whitespace-pre-wrap text-md text-ink-primary">{today.data.prep_text}</p>
          {today.data.prep_session ? <TextLink className="mt-2 inline-block text-sm" href={`/agent/sessions/${today.data.prep_session}`}>{t("channel.openSession")}</TextLink> : null}
        </Card>
      ) : null}
      <UserChannel />
      {today.data ? (
        <>
          {noMail ? (
            <EmptyState icon="today" title={t("today.empty.title")} description={t("today.empty.description")} action={<TextLink href="/settings?section=accounts">{t("mail.noAccount.action")}</TextLink>} />
          ) : (
            <>
              <ThreadList title={t("today.needsYou")} threads={today.data.needs_you} empty={t("today.needsYou.empty")} />
              <ThreadList title={t("today.waiting")} threads={today.data.waiting} empty={t("today.waiting.empty")} />
            </>
          )}
          {today.data.automated_count ? <TextLink className="self-start text-md" href="/mail/categories">{tn("today.automated", today.data.automated_count)}</TextLink> : null}
        </>
      ) : null}
    </div>
  );
}
