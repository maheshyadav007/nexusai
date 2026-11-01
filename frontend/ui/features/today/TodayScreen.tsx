"use client";

import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useState } from "react";
import type { ChannelMessage, MailCategory, TodayThread } from "@/ui/client/contracts.generated";
import { useDateOnly, useDateTime, useShortDate } from "@/ui/client/format";
import { useCategories, useDecideCategory, useMailStatus } from "@/ui/client/mail";
import { groupApprovals, useApprovals, useSessions } from "@/ui/client/sessions";
import { useChannel, useDecideMemory, useDismissChannel, useMemory, useReminders, useRemoveReminder, useRemoveTask, useRespondChannel, useSaveReminder, useSaveTask, useTasks, useToday, useWaitingCount } from "@/ui/client/work";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { ApprovalGroupCard, QuestionCard } from "@/ui/features/assistant/Cards";
import { Composer } from "@/ui/features/assistant/Composer";
import { Icon, type IconName } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { FADE_RISE } from "@/ui/primitives/motion";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { TextLink } from "@/ui/primitives/TextLink";
import { t, tn } from "@/ui/strings";

const TITLE_LENGTH = 60;

function ThreadList({ title, threads, empty }: { title: string; threads: readonly TodayThread[]; empty: string }) {
  const format = useShortDate();
  return (
    <section aria-label={title} className="flex flex-col gap-1">
      <h2 className="text-md font-medium text-ink-primary">{title}</h2>
      {threads.length === 0 ? <p className="py-1 text-md text-ink-muted">{empty}</p> : null}
      <ul className="flex flex-col border-t border-line-subtle">
        {threads.map((thread) => (
          <li key={thread.id} className="border-b border-line-subtle">
            <Link href={`/mail/all/${thread.id}`} data-testid="today-thread" className="focus-ring flex flex-col gap-px py-2 transition-colors duration-fast hover:bg-surface-raised">
              <span className="flex items-baseline justify-between gap-3">
                <span className="flex min-w-0 items-center gap-2">
                  {thread.importance === "high" ? <span aria-label={t("today.important")} role="img" className="h-2 w-2 shrink-0 rounded-full bg-accent-default" /> : null}
                  <span className="truncate text-md text-ink-primary">{thread.subject || t("mail.noSubject")}</span>
                </span>
                <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(thread.last_date)}</span>
              </span>
              {thread.why ? <span className="truncate text-sm text-ink-muted">{thread.why}</span> : null}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AskRow({ message }: { message: ChannelMessage }) {
  const respond = useRespondChannel();
  const dismiss = useDismissChannel();
  const assistant = useAssistant();
  const sessions = useSessions("");
  const title = sessions.data?.sessions.find((row) => row.id === message.session)?.title;
  return (
    <div className="flex flex-col gap-1">
      <p className="flex items-center gap-2 text-sm text-ink-muted">
        {message.session && message.session !== "mail-agent" ? (
          <button type="button" onClick={() => assistant.openSession(message.session as string)} className="focus-ring min-w-0 truncate rounded-sm underline underline-offset-2 transition-colors duration-fast hover:text-ink-primary">
            {title ?? message.agent}
          </button>
        ) : (
          message.agent
        )}
        {message.thread ? <TextLink className="text-sm" href={`/mail/all/${message.thread}`}>{t("channel.openSource")}</TextLink> : null}
      </p>
      <QuestionCard question={message.text} options={message.options} multiple={message.multiple ?? false} pending={respond.isPending} onAnswer={(answer) => respond.mutate({ id: message.id, answer })} onSkip={() => dismiss.mutate(message.id)} />
    </div>
  );
}

function ProposalRow({ icon, title, meta, why, onAccept, onDecline, accept = t("tasks.accept") }: { icon: IconName; title: string; meta: string; why?: string | null | undefined; onAccept: () => void; onDecline: () => void; accept?: string }) {
  return (
    <motion.li {...FADE_RISE} data-testid="proposal" className="flex items-start gap-3 rounded-lg border border-line-subtle bg-surface-raised p-4">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface-sunken text-ink-secondary">
        <Icon name={icon} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="break-words text-md font-medium text-ink-primary">{title}</p>
        <p className="text-sm tabular-nums text-ink-muted">{meta}</p>
        {why ? <p className="text-sm text-ink-secondary">{why}</p> : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Button variant="quiet" onClick={onDecline}>
          {t("memory.decline")}
        </Button>
        <Button variant="primary" onClick={onAccept}>
          {accept}
        </Button>
      </div>
    </motion.li>
  );
}

/** Everything agents are waiting on the person for, in one place, answered right here. */
function WaitingOnYou() {
  const channel = useChannel();
  const approvals = useApprovals();
  const tasks = useTasks(false);
  const reminders = useReminders();
  const memory = useMemory("");
  const categories = useCategories();
  const saveTask = useSaveTask();
  const removeTask = useRemoveTask();
  const saveReminder = useSaveReminder();
  const removeReminder = useRemoveReminder();
  const decideMemory = useDecideMemory();
  const decideCategory = useDecideCategory();
  const formatWhen = useDateTime();
  const formatDay = useDateOnly();
  const asks = (channel.data?.messages ?? []).filter((message) => message.kind === "ask");
  const pending = approvals.data?.approvals ?? [];
  const proposedTasks = (tasks.data?.tasks ?? []).filter((task) => task.proposed);
  const proposedReminders = (reminders.data?.reminders ?? []).filter((reminder) => reminder.proposed);
  const proposedMemories = memory.data?.proposals ?? [];
  const proposedCategories: readonly MailCategory[] = (categories.data?.categories ?? []).filter((item) => item.proposed);
  const count = useWaitingCount();
  if (channel.isError) return <ErrorState title={t("channel.error")} onRetry={() => void channel.refetch()} />;
  return (
    <section aria-label={t("today.waitingOnYou")} className="flex flex-col gap-3">
      <h2 className="flex items-baseline gap-2 text-md font-medium text-ink-primary">
        {t("today.waitingOnYou")}
        {count ? <span className="text-sm tabular-nums text-accent-default">{count}</span> : null}
      </h2>
      {channel.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {channel.isSuccess && count === 0 ? <p className="text-md text-ink-muted">{t("today.nothingWaiting")}</p> : null}
      <AnimatePresence initial={false}>
        {groupApprovals(pending).map((group) => (
          <motion.div key={`approval-${group[0]?.session}-${group[0]?.tool}`} layout {...FADE_RISE} className="flex flex-col gap-1">
            <p className="text-sm text-ink-muted">{group[0]?.session_title}</p>
            <ApprovalGroupCard approvals={group} />
          </motion.div>
        ))}
        {asks.map((message) => (
          <motion.div key={`ask-${message.id}`} layout {...FADE_RISE} data-testid="channel-message">
            <AskRow message={message} />
          </motion.div>
        ))}
      </AnimatePresence>
      <ul className="flex flex-col gap-3">
        {proposedTasks.map((task) => (
          <ProposalRow key={`task-${task.id}`} icon="tasks" title={task.title} meta={task.due ? t("today.proposal.taskDue", { when: formatDay(task.due) }) : t("today.proposal.task")} onDecline={() => removeTask.mutate(task.id)} onAccept={() => saveTask.mutate({ id: task.id, title: task.title, notes: task.notes, status: task.status, due: task.due ?? null, thread: task.thread ?? null, proposed: false })} />
        ))}
        {proposedReminders.map((reminder) => (
          <ProposalRow key={`reminder-${reminder.id}`} icon="reminders" title={reminder.title} meta={t("today.proposal.reminder", { when: formatWhen(reminder.when) })} onDecline={() => removeReminder.mutate(reminder.id)} onAccept={() => saveReminder.mutate({ id: reminder.id, title: reminder.title, when: reminder.when, repeat: reminder.repeat, thread: reminder.thread ?? null, task: reminder.task ?? null, proposed: false })} />
        ))}
        {proposedCategories.map((item) => (
          <ProposalRow key={`category-${item.name}`} icon="categories" title={item.name} meta={item.sender ? t("today.proposal.categoryFrom", { sender: item.sender }) : t("today.proposal.category")} why={item.why} onDecline={() => decideCategory.mutate({ name: item.name, accept: false })} onAccept={() => decideCategory.mutate({ name: item.name, accept: true })} accept={t("categories.create")} />
        ))}
        {proposedMemories.map((item) => (
          <ProposalRow key={`memory-${item.id}`} icon="memory" title={item.text} meta={t("today.proposal.memory")} onDecline={() => decideMemory.mutate({ id: item.id, accept: false })} onAccept={() => decideMemory.mutate({ id: item.id, accept: true })} accept={t("memory.keep")} />
        ))}
      </ul>
    </section>
  );
}

function AgentNotes() {
  const channel = useChannel();
  const dismiss = useDismissChannel();
  const notes = (channel.data?.messages ?? []).filter((message) => message.kind !== "ask");
  if (!notes.length) return null;
  return (
    <section aria-label={t("channel.title")} className="flex flex-col gap-1">
      <h2 className="text-md font-medium text-ink-primary">{t("channel.title")}</h2>
      <ul className="flex flex-col border-t border-line-subtle">
        {notes.map((message) => (
          <li key={message.id} data-testid="channel-message" className="flex items-start justify-between gap-3 border-b border-line-subtle py-2">
            <div className="flex min-w-0 flex-col gap-px">
              <p className="break-words text-md text-ink-primary">{message.text}</p>
              <p className="flex items-center gap-2 text-sm text-ink-muted">
                {message.agent}
                {message.count > 1 ? <span className="tabular-nums">{t("channel.times", { count: message.count })}</span> : null}
                {message.thread ? <TextLink className="text-sm" href={`/mail/all/${message.thread}`}>{t("channel.openSource")}</TextLink> : null}
              </p>
            </div>
            <Button variant="quiet" onClick={() => dismiss.mutate(message.id)}>
              {t("channel.dismiss")}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function WorkingNow() {
  const sessions = useSessions("");
  const assistant = useAssistant();
  const rows = (sessions.data?.sessions ?? []).filter((row) => row.agent !== "mail" && (row.status === "running" || row.status === "queued"));
  if (!rows.length) return null;
  return (
    <ul aria-label={t("today.working")} className="flex flex-wrap gap-2">
      {rows.map((row) => (
        <li key={row.id}>
          <button type="button" onClick={() => assistant.openSession(row.id)} className="focus-ring flex max-w-popover items-center gap-2 rounded-full border border-line-subtle bg-surface-raised px-3 py-1 text-sm text-ink-secondary transition-colors duration-fast hover:text-ink-primary">
            <Icon name="thinking" className="h-3 w-3 shrink-0 animate-working motion-reduce:animate-none" />
            <span className="truncate">{row.title}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Where agents talk to the person: what they need first, then what's worth knowing. */
export function TodayScreen() {
  const today = useToday();
  const mail = useMailStatus();
  const assistant = useAssistant();
  const [text, setText] = useState("");
  const noMail = mail.data?.state === "off" && !today.data?.needs_you.length && !today.data?.waiting.length;
  const send = () => {
    const words = text.trim();
    if (!words) return;
    assistant.start({ text: words, title: words.slice(0, TITLE_LENGTH) });
    setText("");
  };
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="font-serif text-display text-ink-primary">{t("nav.today")}</h1>
        {today.data ? <p data-testid="today-brief" className="text-md tabular-nums text-ink-secondary">{today.data.brief}</p> : null}
      </header>
      <Composer value={text} onChange={setText} onSubmit={send} busy={assistant.starting} placeholder={t("today.ask")} label={t("today.ask")} />
      <WorkingNow />
      {today.isError ? <ErrorState title={t("today.error")} onRetry={() => void today.refetch()} /> : null}
      <WaitingOnYou />
      {today.data?.prep_text ? (
        <section aria-label={t("today.prep")} className="flex flex-col gap-1">
          <h2 className="text-md font-medium text-ink-primary">{t("today.prep")}</h2>
          <p data-testid="today-prep" className="whitespace-pre-wrap text-md text-ink-primary">{today.data.prep_text}</p>
          {today.data.prep_session ? (
            <button type="button" onClick={() => assistant.openSession(today.data?.prep_session as string)} className="focus-ring self-start rounded-sm text-sm text-ink-secondary underline underline-offset-2 hover:text-ink-primary">
              {t("channel.openSession")}
            </button>
          ) : null}
        </section>
      ) : null}
      <AgentNotes />
      {today.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {today.data ? (
        noMail ? (
          <EmptyState icon="today" title={t("today.empty.title")} description={t("today.empty.description")} action={<TextLink href="/settings?section=accounts">{t("mail.noAccount.action")}</TextLink>} />
        ) : (
          <>
            <ThreadList title={t("today.needsYou")} threads={today.data.needs_you} empty={t("today.needsYou.empty")} />
            <ThreadList title={t("today.waiting")} threads={today.data.waiting} empty={t("today.waiting.empty")} />
            {today.data.automated_count ? <TextLink className="self-start text-md" href="/mail/all">{tn("today.automated", today.data.automated_count)}</TextLink> : null}
          </>
        )
      ) : null}
    </div>
  );
}
