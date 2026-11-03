"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { ChannelMessage, DueItem, MailCategory, TodayThread, ToolApproval } from "@/ui/client/contracts.generated";
import { useDateOnly, useDateTime, useShortDate } from "@/ui/client/format";
import { useCategories, useDecideCategory, useMailStatus, useSetImportance, useSetStatus } from "@/ui/client/mail";
import { groupApprovals, useApprovals, useDecideApprovals, useSessions } from "@/ui/client/sessions";
import { useProfile } from "@/ui/client/onboarding";
import { useChannel, useCockpit, useDecideMemory, useDecideSuggestion, useSuggestions, useDismissChannel, useMarkTodaySeen, useMemory, useReactToBrief, useReminders, useRemoveReminder, useRemoveTask, useRespondChannel, useSaveReminder, useSaveTask, useTasks, useToday, useWaitingCount } from "@/ui/client/work";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { ApprovalGroupCard, QuestionCard } from "@/ui/features/assistant/Cards";
import { Markdown } from "@/ui/features/assistant/Markdown";
import { Icon, type IconName } from "@/ui/icons";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Textarea } from "@/ui/primitives/Input";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { Pressable } from "@/ui/primitives/Pressable";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { TextLink } from "@/ui/primitives/TextLink";
import { useToast } from "@/ui/primitives/Toast";
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
      <QuestionCard question={message.text} options={message.options} multiple={message.multiple ?? false} pending={respond.isPending || dismiss.isPending} error={respond.error?.message ?? dismiss.error?.message ?? null} onAnswer={(answer) => respond.mutate({ id: message.id, answer })} onSkip={() => dismiss.mutate(message.id)} />
    </div>
  );
}

/** One thing waiting on the person, however it came to be, so it can be done alone or in bulk. */
interface WaitingItem {
  key: string;
  title: string;
  /** Left out when reading it first matters, or when only the person can answer. */
  doIt?: () => Promise<unknown>;
  decline: () => Promise<unknown>;
}

type Acting = "accept" | "decline" | null;

/** Blocks both buttons while it runs, shows the agents' sign on the one pressed, and says how it went. */
function useRowAction(item: Pick<WaitingItem, "doIt" | "decline">) {
  const [acting, setActing] = useState<Acting>(null);
  const [done, setDone] = useState(false);
  const [failed, setFailed] = useState<{ which: Exclude<Acting, null>; why: string } | null>(null);
  const run = async (which: Exclude<Acting, null>) => {
    const action = which === "accept" ? item.doIt : item.decline;
    if (!action) return;
    setActing(which);
    setFailed(null);
    try {
      await action();
      setDone(true);
    } catch (error) {
      setFailed({ which, why: error instanceof Error ? error.message : String(error) });
    } finally {
      setActing(null);
    }
  };
  return { acting, done, failed, run };
}

function ProposalRow({ icon, title, meta, why, item, accept = t("tasks.accept"), selecting, selected, onToggle }: { icon: IconName; title: string; meta: string; why?: string | null | undefined; item: WaitingItem; accept?: string; selecting: boolean; selected: boolean; onToggle: () => void }) {
  const { acting, done, failed, run } = useRowAction(item);
  const busy = acting !== null || done;
  return (
    <Rise as="li" settle data-testid="proposal" data-state={done ? "done" : failed ? "failed" : acting ? "running" : "idle"} className="flex flex-col gap-2 rounded-lg border border-line-subtle bg-surface-raised p-4">
      <div className="flex items-start gap-3">
        {selecting ? <div className="mt-1 shrink-0"><Checkbox label={t("today.select.item", { title })} hideLabel checked={selected} onChange={onToggle} /></div> : null}
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface-sunken text-ink-secondary">
          <Icon name={icon} />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="break-words text-md font-medium text-ink-primary">{title}</p>
          <p className="text-sm tabular-nums text-ink-muted">{meta}</p>
          {why ? <p className="text-sm text-ink-secondary">{why}</p> : null}
        </div>
        {selecting ? null : (
          <div className="flex shrink-0 items-center gap-2">
            {done ? (
              <span role="status" className="flex items-center gap-1 text-sm text-status-success"><Icon name="check" className="h-4 w-4" />{t("today.action.doneLabel")}</span>
            ) : (
              <>
                <Button variant="quiet" thinking loading={acting === "decline"} disabled={busy} onClick={() => void run("decline")}>{t("memory.decline")}</Button>
                <Button variant="primary" thinking loading={acting === "accept"} disabled={busy} onClick={() => void run("accept")}>{accept}</Button>
              </>
            )}
          </div>
        )}
      </div>
      {failed ? (
        <p role="alert" className="flex flex-wrap items-center gap-2 text-sm text-status-danger">
          {t("today.action.failed", { why: failed.why })}
          <Button variant="quiet" className="py-px" onClick={() => void run(failed.which)}>{t("today.action.again")}</Button>
        </p>
      ) : null}
    </Rise>
  );
}

/** Picks several at once. Runs them one by one, so a failure stays selected and can be tried again. */
function BulkBar({ items, picked, onPick, onClear, onCancel }: { items: readonly WaitingItem[]; picked: ReadonlySet<string>; onPick: (keys: readonly string[]) => void; onClear: () => void; onCancel: () => void }) {
  const toast = useToast();
  const [progress, setProgress] = useState<{ done: number; total: number; which: "accept" | "decline" } | null>(null);
  const chosen = items.filter((item) => picked.has(item.key));
  const doable = chosen.filter((item) => item.doIt);
  const run = async (which: "accept" | "decline") => {
    const list = which === "accept" ? doable : chosen;
    const failed: string[] = [];
    setProgress({ done: 0, total: list.length, which });
    for (const [index, item] of list.entries()) {
      try {
        await (which === "accept" ? item.doIt?.() : item.decline());
      } catch {
        failed.push(item.key);
      }
      setProgress({ done: index + 1, total: list.length, which });
    }
    setProgress(null);
    if (failed.length) {
      onPick(failed);
      toast({ title: t("today.select.partly", { done: list.length - failed.length, failed: failed.length }), tone: "danger" });
    } else {
      onCancel();
      toast({ title: t("today.select.done", { done: list.length }) });
    }
  };
  const busy = progress !== null;
  const counting = progress ? t("today.select.progress", { done: progress.done, total: progress.total }) : null;
  return (
    <div data-testid="bulk-bar" className="sticky top-0 z-10 flex flex-wrap items-center gap-2 rounded-lg border border-line-subtle bg-surface-raised p-2 shadow-raised">
      <span role="status" className="px-2 text-sm tabular-nums text-ink-secondary">{chosen.length ? t("today.select.count", { count: chosen.length }) : t("today.select.none")}</span>
      <Button variant="quiet" disabled={busy} onClick={() => onPick(chosen.length === items.length ? [] : items.map((item) => item.key))}>{t("today.select.all")}</Button>
      <span className="flex-1" />
      <Button variant="quiet" disabled={busy} onClick={() => { onClear(); onCancel(); }}>{t("today.select.cancel")}</Button>
      <Button thinking loading={progress?.which === "decline"} disabled={busy || !chosen.length} onClick={() => void run("decline")}>{progress?.which === "decline" ? counting : t("today.select.decline", { count: chosen.length })}</Button>
      <Button variant="primary" thinking loading={progress?.which === "accept"} disabled={busy || !doable.length} onClick={() => void run("accept")}>{progress?.which === "accept" ? counting : t("today.select.doIt", { count: doable.length })}</Button>
    </div>
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
  const decideApprovals = useDecideApprovals();
  const dismiss = useDismissChannel();
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
  const [selecting, setSelecting] = useState(false);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const groups = groupApprovals(pending);
  const groupKey = (group: readonly ToolApproval[]) => `approval-${group[0]?.session}-${group[0]?.tool}`;
  const taskItem = (task: (typeof proposedTasks)[number]): WaitingItem => ({ key: `task-${task.id}`, title: task.title, doIt: () => saveTask.mutateAsync({ id: task.id, title: task.title, notes: task.notes, status: task.status, due: task.due ?? null, thread: task.thread ?? null, proposed: false }), decline: () => removeTask.mutateAsync(task.id) });
  const reminderItem = (reminder: (typeof proposedReminders)[number]): WaitingItem => ({ key: `reminder-${reminder.id}`, title: reminder.title, doIt: () => saveReminder.mutateAsync({ id: reminder.id, title: reminder.title, when: reminder.when, repeat: reminder.repeat, thread: reminder.thread ?? null, task: reminder.task ?? null, proposed: false }), decline: () => removeReminder.mutateAsync(reminder.id) });
  const categoryItem = (item: MailCategory): WaitingItem => ({ key: `category-${item.name}`, title: item.name, doIt: () => decideCategory.mutateAsync({ name: item.name, accept: true }), decline: () => decideCategory.mutateAsync({ name: item.name, accept: false }) });
  const suggestionItem = (item: NonNullable<typeof suggestions.data>["suggestions"][number]): WaitingItem => ({ key: `suggestion-${item.id}`, title: t("today.suggestion.title", { category: item.category, count: item.emails }), doIt: () => decideSuggestion.mutateAsync({ id: item.id, accept: true }), decline: () => decideSuggestion.mutateAsync({ id: item.id, accept: false }) });
  const memoryItem = (item: (typeof proposedMemories)[number]): WaitingItem => ({ key: `memory-${item.id}`, title: item.text, doIt: () => decideMemory.mutateAsync({ id: item.id, accept: true }), decline: () => decideMemory.mutateAsync({ id: item.id, accept: false }) });
  const approvalItem = (group: readonly ToolApproval[]): WaitingItem => {
    const ids = group.map((row) => row.id);
    // Mail going out and commands running are read one at a time, never waved through in a batch.
    const careful = group.some((row) => row.preview?.kind === "mail" || row.preview?.kind === "command");
    return { key: groupKey(group), title: group[0]?.tool_label ?? group[0]?.tool ?? "", ...(careful ? {} : { doIt: () => decideApprovals.mutateAsync({ allow: ids }) }), decline: () => decideApprovals.mutateAsync({ deny: ids }) };
  };
  const askItem = (message: ChannelMessage): WaitingItem => ({ key: `ask-${message.id}`, title: message.text, decline: () => dismiss.mutateAsync(message.id) });
  const allItems: readonly WaitingItem[] = [
    ...groups.map(approvalItem),
    ...asks.map(askItem),
    ...proposedTasks.map(taskItem),
    ...proposedReminders.map(reminderItem),
    ...proposedCategories.map(categoryItem),
    ...(suggestions.data?.suggestions ?? []).map(suggestionItem),
    ...proposedMemories.map(memoryItem),
  ];
  const toggle = (key: string) =>
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const row = (item: WaitingItem) => ({ item, selecting, selected: picked.has(item.key), onToggle: () => toggle(item.key) });
  if (channel.isError) return <ErrorState title={t("channel.error")} onRetry={() => void channel.refetch()} />;
  return (
    <section aria-label={t("today.needsYou")} className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="flex items-baseline gap-2 text-md font-medium text-ink-primary">
          {t("today.needsYou")}
          {count ? <span className="text-sm tabular-nums text-accent-default">{count}</span> : null}
        </h2>
        {allItems.length > 1 && !selecting ? <Button variant="quiet" className="py-px" data-testid="bulk-select" onClick={() => setSelecting(true)}>{t("today.select")}</Button> : null}
      </div>
      {selecting ? (
        <>
          <BulkBar items={allItems} picked={picked} onPick={(keys) => setPicked(new Set(keys))} onClear={() => setPicked(new Set())} onCancel={() => { setSelecting(false); setPicked(new Set()); }} />
          {allItems.filter((item) => picked.has(item.key)).some((item) => !item.doIt) ? <p className="text-sm text-ink-muted">{t("today.select.review")}</p> : null}
        </>
      ) : null}
      {channel.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {channel.isSuccess && count === 0 ? <p className="text-md text-ink-muted">{t("today.nothingWaiting")}</p> : null}
      <Presence>
        {groups.map((group) => {
          const item = approvalItem(group);
          return (
            <Rise key={item.key} settle className="flex flex-col gap-1">
              <p className="flex items-center gap-2 text-sm text-ink-muted">
                {selecting ? <Checkbox label={t("today.select.item", { title: item.title })} hideLabel checked={picked.has(item.key)} onChange={() => toggle(item.key)} /> : null}
                {group[0]?.session_title}
              </p>
              <ApprovalGroupCard approvals={group} />
            </Rise>
          );
        })}
        {asks.map((message) => {
          const item = askItem(message);
          return (
            <Rise key={item.key} settle data-testid="channel-message" className="flex items-start gap-2">
              {selecting ? <div className="mt-1 shrink-0"><Checkbox label={t("today.select.item", { title: item.title })} hideLabel checked={picked.has(item.key)} onChange={() => toggle(item.key)} /></div> : null}
              <div className="min-w-0 flex-1"><AskRow message={message} /></div>
            </Rise>
          );
        })}
      </Presence>
      <ul className="flex flex-col gap-3">
        <Presence>
          {proposedTasks.map((task) => {
            const item = taskItem(task);
            return <ProposalRow key={item.key} {...row(item)} icon="tasks" title={task.title} meta={task.due ? t("today.proposal.taskDue", { when: formatDay(task.due) }) : t("today.proposal.task")} />;
          })}
          {proposedReminders.map((reminder) => {
            const item = reminderItem(reminder);
            return <ProposalRow key={item.key} {...row(item)} icon="reminders" title={reminder.title} meta={t("today.proposal.reminder", { when: formatWhen(reminder.when) })} />;
          })}
          {proposedCategories.map((category) => {
            const item = categoryItem(category);
            return <ProposalRow key={item.key} {...row(item)} icon="categories" title={category.name} meta={category.sender ? t("today.proposal.categoryFrom", { sender: category.sender }) : t("today.proposal.category")} why={category.why} accept={t("categories.create")} />;
          })}
          {(suggestions.data?.suggestions ?? []).map((suggestion) => {
            const item = suggestionItem(suggestion);
            return <ProposalRow key={item.key} {...row(item)} icon="categories" title={item.title} meta={t("today.suggestion.meta", { senders: suggestion.senders.length, opened: suggestion.opened, replied: suggestion.replied })} why={suggestion.quiet ? t("today.suggestion.quiet", { why: suggestion.reason, count: suggestion.to_archive }) : suggestion.reason} accept={t("today.suggestion.accept")} />;
          })}
          {proposedMemories.map((proposal) => {
            const item = memoryItem(proposal);
            return <ProposalRow key={item.key} {...row(item)} icon="memory" title={proposal.text} meta={t("today.proposal.memory")} accept={t("memory.keep")} />;
          })}
        </Presence>
      </ul>
    </section>
  );
}

/** Today's brief, first thing on the page, and how the next one gets better. */
function MorningBrief() {
  const today = useToday();
  const assistant = useAssistant();
  const react = useReactToBrief();
  const toast = useToast();
  const format = useDateTime();
  const data = today.data;
  const [comment, setComment] = useState("");
  const [telling, setTelling] = useState(false);
  const rating = (data?.prep_rating ?? null) as "up" | "down" | null;
  const session = data?.prep_session;
  const said = data?.prep_comment ?? "";
  useEffect(() => setComment(said), [said]);
  if (!data?.prep_text || !session) return null;
  const send = (next: { rating: "up" | "down" | null; comment: string }, after?: () => void) =>
    react.mutate({ session, ...next }, { onSuccess: () => { toast({ title: t("today.brief.saved") }); after?.(); }, onError: () => toast({ title: t("today.brief.failed"), tone: "danger" }) });
  const rate = (value: "up" | "down") => {
    const next = rating === value ? null : value;
    send({ rating: next, comment: said });
    // Not liking it is when there's most to say.
    if (next === "down") setTelling(true);
  };
  return (
    <section aria-label={t("today.prep")} data-testid="morning-brief" className="ai-surface flex flex-col gap-3 rounded-lg p-5">
      <header className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-medium text-ink-primary"><Icon name="thinking" className="h-4 w-4 text-accent-default" />{t("today.prep")}</h2>
        {data.prep_at ? <span className="text-sm tabular-nums text-ink-muted">{t("today.brief.when", { when: format(data.prep_at) })}</span> : null}
      </header>
      <div data-testid="today-prep" className="text-md text-ink-primary"><Markdown text={data.prep_text} /></div>
      <div className="flex flex-wrap items-center gap-1">
        <IconButton icon="like" label={t("today.brief.like")} aria-pressed={rating === "up"} data-testid="brief-like" className={rating === "up" ? "text-accent-default" : ""} disabled={react.isPending} onClick={() => rate("up")} />
        <IconButton icon="dislike" label={t("today.brief.dislike")} aria-pressed={rating === "down"} data-testid="brief-dislike" className={rating === "down" ? "text-accent-default" : ""} disabled={react.isPending} onClick={() => rate("down")} />
        <Button variant="quiet" aria-expanded={telling} data-testid="brief-tell" onClick={() => setTelling(!telling)}>{t("today.brief.tell")}</Button>
        <span className="flex-1" />
        <Pressable onClick={() => assistant.openSession(session)} className="focus-ring rounded-sm text-sm text-ink-secondary underline underline-offset-2 hover:text-ink-primary">{t("channel.openSession")}</Pressable>
      </div>
      {telling ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            send({ rating, comment }, () => setTelling(false));
          }}
        >
          <Textarea data-testid="brief-comment" aria-label={t("today.brief.tell")} placeholder={t("today.brief.hint")} rows={2} value={comment} onChange={(event) => setComment(event.target.value)} />
          <div><Button type="submit" thinking loading={react.isPending} disabled={!comment.trim() || comment.trim() === said}>{t("today.brief.send")}</Button></div>
        </form>
      ) : said ? <p data-testid="brief-said" className="text-sm text-ink-secondary">{said}</p> : null}
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
      <MorningBrief />
      <FinishSetup />
      {today.isError ? <ErrorState title={t("today.error")} onRetry={() => void today.refetch()} /> : null}
      <WaitingOnYou />
      <DueToday items={today.data?.due ?? []} />
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
