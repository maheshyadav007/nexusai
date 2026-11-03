"use client";

import Link from "next/link";
import { useEffect } from "react";
import type { ChannelMessage, DueItem, MailCategory, TodayThread } from "@/ui/client/contracts.generated";
import { useDateOnly, useDateTime, useShortDate } from "@/ui/client/format";
import { useCategories, useDecideCategory, useMailStatus, useSetImportance, useSetStatus } from "@/ui/client/mail";
import { groupApprovals, useApprovals, useSessions } from "@/ui/client/sessions";
import { useProfile } from "@/ui/client/onboarding";
import { useChannel, useCockpit, useDecideMemory, useDecideSuggestion, useSuggestions, useDismissChannel, useMarkTodaySeen, useMemory, useReminders, useRemoveReminder, useRemoveTask, useRespondChannel, useSaveReminder, useSaveTask, useTasks, useToday, useWaitingCount } from "@/ui/client/work";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { ApprovalGroupCard, QuestionCard } from "@/ui/features/assistant/Cards";
import { Icon, type IconName } from "@/ui/icons";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { Pressable } from "@/ui/primitives/Pressable";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { TextLink } from "@/ui/primitives/TextLink";
import { t, tn, type StringKey } from "@/ui/strings";
import { FinishSetup } from "./FinishSetup";

const MAIL_AGENT = "mail-agent";
// How long a conversation can sit quietly before it's worth a nudge.
const QUIET_DAYS = 3;

const NEXT_ACTION_LABEL: Partial<Record<string, StringKey>> = { reply: "today.action.reply", do: "today.action.do", decide: "today.action.decide", read: "today.action.read" };

function ThreadList({ title, threads, empty, chase = false }: { title: string; threads: readonly TodayThread[]; empty: string; chase?: boolean }) {
  const format = useShortDate();
  const setStatus = useSetStatus();
  const setImportance = useSetImportance();
  return (
    <section aria-label={title} className="flex flex-col gap-1">
      <h2 className="text-md font-medium text-ink-primary">{title}</h2>
      {threads.length === 0 ? <p className="py-1 text-md text-ink-muted">{empty}</p> : null}
      <ul className="flex flex-col border-t border-line-subtle">
        {threads.map((thread) => {
          const action = thread.next_action ? NEXT_ACTION_LABEL[thread.next_action] : undefined;
          return (
            <li key={thread.id} className="group flex items-start gap-2 border-b border-line-subtle">
              <Link href={`/mail/all/${thread.id}`} data-testid="today-thread" className="focus-ring flex min-w-0 flex-1 flex-col gap-px py-2 transition-colors duration-fast hover:bg-surface-hover">
                <span className="flex items-baseline justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-2">
                    {thread.importance === "high" ? <span aria-label={t("today.important")} role="img" className="h-2 w-2 shrink-0 rounded-full bg-accent-default" /> : null}
                    <span className="truncate text-md text-ink-primary">{thread.subject || t("mail.noSubject")}</span>
                    {action ? <Badge>{t(action)}</Badge> : null}
                  </span>
                  <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(thread.last_date)}</span>
                </span>
                {thread.why ? <span className="truncate text-sm text-ink-muted">{thread.why}</span> : null}
              </Link>
              <span className="flex shrink-0 items-center gap-1 py-2">
                {chase ? <AskAgent context={[`mail:${thread.id}`]} title={t("today.chase.title")} label={t("today.chase.draft")} text={t("today.chase.ask")} /> : null}
                {thread.importance !== "low" && !chase ? <Button variant="quiet" onClick={() => setImportance.mutate({ id: thread.id, importance: "low" })}>{t("today.notImportant")}</Button> : null}
                <Button variant="quiet" onClick={() => setStatus.mutate({ id: thread.id, status: "resolved" })}>{t("today.done")}</Button>
              </span>
            </li>
          );
        })}
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
        {message.session ? (
          <Pressable onClick={() => assistant.openSession(message.session as string)} className="focus-ring min-w-0 truncate rounded-sm underline underline-offset-2 transition-colors duration-fast hover:text-ink-primary">
            {title ?? message.agent}
          </Pressable>
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
    <Rise as="li" data-testid="proposal" className="flex items-start gap-3 rounded-lg border border-line-subtle bg-surface-raised p-4">
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
    </Rise>
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
  const suggestions = useSuggestions();
  const decideSuggestion = useDecideSuggestion();
  const proposedCategories: readonly MailCategory[] = (categories.data?.categories ?? []).filter((item) => item.proposed);
  const count = useWaitingCount();
  if (channel.isError) return <ErrorState title={t("channel.error")} onRetry={() => void channel.refetch()} />;
  return (
    <section aria-label={t("today.needsYou")} className="flex flex-col gap-3">
      <h2 className="flex items-baseline gap-2 text-md font-medium text-ink-primary">
        {t("today.needsYou")}
        {count ? <span className="text-sm tabular-nums text-accent-default">{count}</span> : null}
      </h2>
      {channel.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {channel.isSuccess && count === 0 ? <p className="text-md text-ink-muted">{t("today.nothingWaiting")}</p> : null}
      <Presence>
        {groupApprovals(pending).map((group) => (
          <Rise key={`approval-${group[0]?.session}-${group[0]?.tool}`} settle className="flex flex-col gap-1">
            <p className="text-sm text-ink-muted">{group[0]?.session_title}</p>
            <ApprovalGroupCard approvals={group} />
          </Rise>
        ))}
        {asks.map((message) => (
          <Rise key={`ask-${message.id}`} settle data-testid="channel-message">
            <AskRow message={message} />
          </Rise>
        ))}
      </Presence>
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
        {(suggestions.data?.suggestions ?? []).map((item) => (
          <ProposalRow
            key={`suggestion-${item.id}`}
            icon="categories"
            title={t("today.suggestion.title", { category: item.category, count: item.emails })}
            meta={t("today.suggestion.meta", { senders: item.senders.length, opened: item.opened, replied: item.replied })}
            why={item.quiet ? t("today.suggestion.quiet", { why: item.reason, count: item.to_archive }) : item.reason}
            accept={t("today.suggestion.accept")}
            onAccept={() => decideSuggestion.mutate({ id: item.id, accept: true })}
            onDecline={() => decideSuggestion.mutate({ id: item.id, accept: false })}
          />
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

/** What's overdue and what's due today, across tasks, reminders and deadlines from mail. */
function DueToday({ items }: { items: readonly DueItem[] }) {
  const formatDay = useDateOnly();
  const formatWhen = useDateTime();
  if (!items.length) return null;
  return (
    <section aria-label={t("today.due")} className="flex flex-col gap-1">
      <h2 className="text-md font-medium text-ink-primary">{t("today.due")}</h2>
      <ul className="flex flex-col border-t border-line-subtle">
        {items.map((item) => (
          <li key={`${item.kind}-${item.title}-${item.when}`} data-testid="due-item" className="border-b border-line-subtle">
            <Link href={item.link} className="focus-ring flex items-baseline justify-between gap-3 py-2 transition-colors duration-fast hover:bg-surface-raised">
              <span className="min-w-0 truncate text-md text-ink-primary">{item.title}</span>
              <span className={`shrink-0 text-sm tabular-nums ${item.overdue ? "text-status-danger" : "text-ink-muted"}`}>
                {item.overdue ? t("today.due.overdue", { when: formatDay(item.when) }) : item.kind === "reminder" ? formatWhen(item.when) : t("today.due.today")}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SinceYouLooked() {
  const today = useToday();
  const assistant = useAssistant();
  const since = today.data?.since_last_look;
  if (!since?.mail && !since?.judged) return null;
  return (
    <section aria-label={t("today.since")} data-testid="since-last-look" className="flex flex-col gap-1">
      <h2 className="text-md font-medium text-ink-primary">{t("today.since")}</h2>
      <p className="text-md tabular-nums text-ink-secondary">{t("today.since.counts", { mail: since.mail ?? 0, important: since.important ?? 0, filed: since.filed ?? 0 })}</p>
      {since.proposed ? <p className="text-md tabular-nums text-ink-secondary">{tn("today.since.proposed", since.proposed)}</p> : null}
      <Pressable onClick={() => assistant.openSession(MAIL_AGENT)} className="self-start rounded-sm text-sm text-ink-secondary underline underline-offset-2 hover:text-ink-primary">{t("today.since.open")}</Pressable>
    </section>
  );
}

/** One line on how the app is doing. The Cockpit has the rest. */
function StatusLine() {
  const cockpit = useCockpit();
  const data = cockpit.data;
  if (!data) return null;
  const health = (id: string) => data.health.find((item) => item.id === id);
  const parts = [health("mail"), health("index-mail")].filter((item) => item !== undefined).map((item) => `${item.label}: ${item.detail}`);
  if (data.jobs.length) parts.push(tn("today.status.running", data.jobs.length));
  return (
    <Link href="/cockpit" data-testid="today-status" className="focus-ring flex items-center gap-2 self-start rounded-sm text-sm text-ink-muted transition-colors duration-fast hover:text-ink-primary">
      <StatusDot tone={data.health.some((item) => item.state === "problem") ? "failed" : data.jobs.length ? "running" : "done"} />
      {parts.join(" · ")}
      <Icon name="chevronRight" className="h-3 w-3" />
    </Link>
  );
}

function useGreeting(): string {
  const profile = useProfile();
  const name = profile.data?.name?.trim().split(" ")[0];
  const hour = new Date().getHours();
  const part = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
  return name ? t(`today.greeting.${part}.named` as StringKey, { name }) : t(`today.greeting.${part}` as StringKey);
}

/** Your day, in order of what needs doing. Agents talk to the person here. */
export function TodayScreen() {
  const today = useToday();
  const mail = useMailStatus();
  const assistant = useAssistant();
  const greeting = useGreeting();
  const { mutate: markSeen } = useMarkTodaySeen();
  // Marked on leaving, so what came in stays listed while the person is reading it.
  useEffect(() => () => markSeen(), [markSeen]);
  const noMail = mail.data?.state === "off" && !today.data?.needs_you.length && !today.data?.waiting.length;
  const waitingOnOthers = (today.data?.waiting ?? []).filter((thread) => (thread.quiet_days ?? 0) >= QUIET_DAYS);
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="font-serif text-display text-ink-primary">{greeting}</h1>
        {today.data ? <p data-testid="today-brief" className="text-md tabular-nums text-ink-secondary">{today.data.brief}</p> : null}
      </header>
      <FinishSetup />
      {today.isError ? <ErrorState title={t("today.error")} onRetry={() => void today.refetch()} /> : null}
      <WaitingOnYou />
      <DueToday items={today.data?.due ?? []} />
      {today.data?.prep_text ? (
        <section aria-label={t("today.prep")} className="flex flex-col gap-1">
          <h2 className="text-md font-medium text-ink-primary">{t("today.prep")}</h2>
          <p data-testid="today-prep" className="whitespace-pre-wrap text-md text-ink-primary">{today.data.prep_text}</p>
          {today.data.prep_session ? (
            <Pressable onClick={() => assistant.openSession(today.data?.prep_session as string)} className="focus-ring self-start rounded-sm text-sm text-ink-secondary underline underline-offset-2 hover:text-ink-primary">
              {t("channel.openSession")}
            </Pressable>
          ) : null}
        </section>
      ) : null}
      <AgentNotes />
      {today.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {today.data ? (
        noMail ? (
          <EmptyState icon="today" title={t("today.empty.title")} description={t("today.empty.description")} action={<TextLink href="/connectors">{t("mail.noAccount.action")}</TextLink>} />
        ) : (
          <>
            <ThreadList title={t("today.importantMail")} threads={today.data.needs_you} empty={t("today.needsYou.empty")} />
            {today.data.follow_ups?.length ? <ThreadList chase title={t("today.followUps")} threads={today.data.follow_ups} empty="" /> : null}
            {waitingOnOthers.length ? <ThreadList title={t("today.waiting")} threads={waitingOnOthers} empty="" /> : null}
            <SinceYouLooked />
            {today.data.automated_count ? <TextLink className="self-start text-md" href="/mail/all">{tn("today.automated", today.data.automated_count)}</TextLink> : null}
          </>
        )
      ) : null}
      <StatusLine />
    </div>
  );
}
