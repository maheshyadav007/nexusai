"use client";

import { MailOrganizationCard } from "./MailOrganizationCard";
import Link from "next/link";
import appConfig from "@/app.config.json";
import { useEffect, useState, type ReactNode } from "react";
import type { ChannelMessage, DueItem, MailCategory, TodayThread, ToolApproval } from "@/ui/client/contracts.generated";
import { useDateOnly, useDateTime, useShortDate } from "@/ui/client/format";
import { useCategories, useDecideCategory, useDecidePriority, useMailStatus, useSetImportance, useSetStatus } from "@/ui/client/mail";
import { groupApprovals, useApprovals, useDecideApprovals, useSessions } from "@/ui/client/sessions";
import { useProfile } from "@/ui/client/onboarding";
import { useChannel, useCockpit, useDecideMemory, useDecideSuggestion, useSuggestions, useDismissChannel, useMarkTodaySeen, useMemory, useReactToBrief, useReminders, useRemoveReminder, useRemoveTask, useRespondChannel, useSaveReminder, useSaveTask, useTasks, useToday, useWaitingCount } from "@/ui/client/work";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { ApprovalGroupCard, QuestionCard } from "@/ui/features/assistant/Cards";
import { Markdown } from "@/ui/features/assistant/Markdown";
import { Icon, type IconName } from "@/ui/icons";
import { AttentionCount } from "@/ui/primitives/AttentionCount";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Textarea } from "@/ui/primitives/Input";
import { CountPop, Presence, Rise } from "@/ui/primitives/Motion";
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

/** A part of the day: what it is, how many, and what can be done about it, all at a glance. */
function Panel({ id, icon, title, count, urgent = false, hint, action, children }: { id?: string; icon: IconName; title: string; count?: number; urgent?: boolean; hint?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} aria-label={title} className={`flex scroll-mt-4 flex-col gap-3 rounded-lg border bg-surface-raised p-4 shadow-raised ${urgent ? "border-accent-default" : "border-line-subtle"}`}>
      <header className="flex items-start gap-3">
        <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${urgent ? "bg-accent-default text-accent-on" : "bg-surface-sunken text-ink-secondary"}`}>
          <Icon name={icon} />
        </span>
        <div className="flex min-w-0 flex-1 flex-col">
          <h2 className="flex items-center gap-2 text-lg font-medium text-ink-primary">
            {title}
            {count ? (urgent ? <AttentionCount value={count} /> : <span className="text-md tabular-nums text-ink-muted">{count}</span>) : null}
          </h2>
          {hint ? <p className="text-sm text-ink-secondary">{hint}</p> : null}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

/** One figure in the line beside the greeting. It takes you to what it counts. */
function Stat({ href, label, value, urgent = false, alarming = false }: { href: string; label: string; value: number; urgent?: boolean; alarming?: boolean }) {
  const tone = !value ? "text-ink-faint" : alarming ? "text-status-danger" : urgent ? "text-accent-default" : "text-ink-primary";
  return (
    <Link href={href} data-testid="today-stat" className="focus-ring group flex items-baseline gap-2 rounded-sm px-4 first:pl-0 last:pr-0">
      <CountPop value={value} className={`text-xl font-medium tabular-nums ${tone}`} />
      <span className="text-sm text-ink-secondary underline-offset-4 transition-colors duration-fast group-hover:text-ink-primary group-hover:underline">{label}</span>
    </Link>
  );
}

const NEXT_ACTION_LABEL: Partial<Record<string, StringKey>> = { reply: "today.action.reply", do: "today.action.do", decide: "today.action.decide", read: "today.action.read" };

function ThreadList({ id, icon, title, hint, urgent = false, threads, empty, chase = false }: { id?: string; icon: IconName; title: string; hint?: string; urgent?: boolean; threads: readonly TodayThread[]; empty: string; chase?: boolean }) {
  const format = useShortDate();
  const setStatus = useSetStatus();
  const setImportance = useSetImportance();
  return (
    <Panel {...(id ? { id } : {})} icon={icon} title={title} count={threads.length} urgent={urgent && threads.length > 0} {...(hint && threads.length ? { hint } : {})}>
      {threads.length === 0 ? <p className="text-md text-ink-muted">{empty}</p> : null}
      <ul className="flex flex-col">
        {threads.map((thread) => {
          const action = thread.next_action ? NEXT_ACTION_LABEL[thread.next_action] : undefined;
          return (
            <li key={thread.id} className="flex flex-col gap-2 border-t border-line-subtle py-3">
              <Link href={`/mail/all/${thread.id}`} data-testid="today-thread" className="focus-ring flex min-w-0 flex-col gap-px rounded-sm transition-colors duration-fast hover:text-accent-default">
                <span className="flex items-baseline justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-2">
                    {thread.importance === "high" ? <span aria-label={t("today.important")} role="img" className="h-2 w-2 shrink-0 rounded-full bg-accent-default" /> : null}
                    <span className="truncate text-md font-medium text-ink-primary">{thread.subject || t("mail.noSubject")}</span>
                    {action ? <Badge tone="accent">{t(action)}</Badge> : null}
                  </span>
                  <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(thread.last_date)}</span>
                </span>
                {thread.why ? <span className="truncate text-sm text-ink-secondary">{thread.why}</span> : null}
              </Link>
              <span className="flex flex-wrap items-center gap-2">
                {chase ? <AskAgent context={[`mail:${thread.id}`]} title={t("today.chase.title")} label={t("today.chase.draft")} text={t("today.chase.ask")} /> : <Link href={`/mail/all/${thread.id}?draft`} data-testid="today-draft" className="focus-ring press ai-glow relative inline-flex items-center rounded-md px-3 py-2 text-md font-medium text-ink-primary">{t("mail.draftReply")}</Link>}
                <Button onClick={() => setStatus.mutate({ id: thread.id, status: "resolved" })}>{t("today.done")}</Button>
                {thread.importance !== "low" && !chase ? <Button variant="quiet" onClick={() => setImportance.mutate({ id: thread.id, importance: "low" })}>{t("today.notImportant")}</Button> : null}
              </span>
            </li>
          );
        })}
      </ul>
    </Panel>
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
  const decidePriority = useDecidePriority();
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
  const priorityPicks: readonly MailCategory[] = (categories.data?.categories ?? []).filter((item) => item.priority_suggested);
  const count = useWaitingCount();
  const [selecting, setSelecting] = useState(false);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const groups = groupApprovals(pending);
  const groupKey = (group: readonly ToolApproval[]) => `approval-${group[0]?.session}-${group[0]?.tool}`;
  const taskItem = (task: (typeof proposedTasks)[number]): WaitingItem => ({ key: `task-${task.id}`, title: task.title, doIt: () => saveTask.mutateAsync({ id: task.id, title: task.title, notes: task.notes, status: task.status, due: task.due ?? null, thread: task.thread ?? null, proposed: false }), decline: () => removeTask.mutateAsync(task.id) });
  const reminderItem = (reminder: (typeof proposedReminders)[number]): WaitingItem => ({ key: `reminder-${reminder.id}`, title: reminder.title, doIt: () => saveReminder.mutateAsync({ id: reminder.id, title: reminder.title, when: reminder.when, repeat: reminder.repeat, thread: reminder.thread ?? null, task: reminder.task ?? null, proposed: false }), decline: () => removeReminder.mutateAsync(reminder.id) });
  const categoryItem = (item: MailCategory): WaitingItem => ({ key: `category-${item.name}`, title: item.name, doIt: () => decideCategory.mutateAsync({ name: item.name, accept: true }), decline: () => decideCategory.mutateAsync({ name: item.name, accept: false }) });
  const priorityItem = (item: MailCategory): WaitingItem => ({ key: `priority-${item.name}`, title: t("today.priority.title", { category: item.name }), doIt: () => decidePriority.mutateAsync({ name: item.name, accept: true }), decline: () => decidePriority.mutateAsync({ name: item.name, accept: false }) });
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
    ...priorityPicks.map(priorityItem),
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
    <Panel id="today-needs" icon="approvals" title={t("today.needsYou")} count={count} urgent={count > 0} {...(count ? { hint: t("today.needsYou.hint") } : {})} action={allItems.length > 1 && !selecting ? <Button variant="quiet" className="py-px" data-testid="bulk-select" onClick={() => setSelecting(true)}>{t("today.select")}</Button> : undefined}>
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
          // While picking, each approval is one line: its own ticks would look like part of the selection.
          if (selecting) {
            return (
              <ul key={item.key}>
                <ProposalRow {...row(item)} icon="approvals" title={tn("approvals.group", group.length, { label: item.title })} meta={group[0]?.session_title ?? ""} />
              </ul>
            );
          }
          return (
            <Rise key={item.key} settle className="flex flex-col gap-1">
              <p className="flex items-center gap-2 text-sm text-ink-muted">{group[0]?.session_title}</p>
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
          {priorityPicks.map((category) => {
            const item = priorityItem(category);
            return <ProposalRow key={item.key} {...row(item)} icon="priority" title={item.title} meta={t("today.priority.meta", { needed: category.needed_you ?? 0, total: category.count ?? 0 })} why={category.priority_why} accept={t("today.priority.accept")} />;
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
    </Panel>
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
  // Presentation acknowledgement belongs to this exact brief, not to a rating or a future run.
  const version = session && data?.prep_at ? `${session}:${data.prep_at}` : null;
  const [interacted, setInteracted] = useState<string[]>([]);
  useEffect(() => {
    try {
      const stored: unknown = JSON.parse(localStorage.getItem(appConfig.storageKeys.briefAttention) ?? "[]");
      if (Array.isArray(stored)) setInteracted(stored.filter((key): key is string => typeof key === "string").slice(0, 50));
    } catch { /* Storage being unavailable only resets the visual acknowledgement. */ }
  }, []);
  const attended = Boolean(version && interacted.includes(version));
  const acknowledge = () => {
    if (!version || attended) return;
    const next = [version, ...interacted].slice(0, 50);
    setInteracted(next);
    try { localStorage.setItem(appConfig.storageKeys.briefAttention, JSON.stringify(next)); } catch { /* Keep the in-memory acknowledgement. */ }
  };

  useEffect(() => setComment(said), [said]);
  if (!data?.prep_text || !session) return data?.prep_freshness === "failed" ? <section className="rounded-lg border border-line-subtle p-5" role="status"><h2 className="text-lg font-medium text-ink-primary">{t("today.prep")}</h2><p className="mt-2 text-sm text-ink-secondary">{t("today.brief.freshness.failed")}</p></section> : null;
  const send = (next: { rating: "up" | "down" | null; comment: string }, after?: () => void) =>
    react.mutate({ session, artifact: data.prep_artifact ?? undefined, ...next }, { onSuccess: () => { toast({ title: t("today.brief.saved") }); after?.(); }, onError: () => toast({ title: t("today.brief.failed"), tone: "danger" }) });
  const rate = (value: "up" | "down") => {
    const next = rating === value ? null : value;
    send({ rating: next, comment: said });
    // Not liking it is when there's most to say.
    if (next === "down") setTelling(true);
  };
  return (
    <fieldset aria-label={t("today.prep")} data-testid="morning-brief" data-attended={attended} onClick={acknowledge} onCopy={acknowledge} onInput={acknowledge} onFocusCapture={(event) => { if (event.target.matches(":focus-visible")) acknowledge(); }} className={`${attended ? "ai-result" : "ai-surface ai-brief-attention"} flex min-w-0 flex-col gap-3 rounded-lg p-5`}>
      {attended ? <legend className="px-2 text-sm font-medium text-ink-secondary">{t("today.prep")}</legend> : null}
      <header className="flex items-center justify-between gap-3">
        {!attended ? <h2 className="flex items-center gap-2 text-lg font-medium text-ink-primary"><Icon name="thinking" className="h-4 w-4 text-accent-default" />{t("today.prep")}</h2> : null}
        {data.prep_at ? <span className="text-sm tabular-nums text-ink-muted">{t("today.brief.when", { when: format(data.prep_at) })}</span> : null}
      </header>
      {data.prep_freshness && data.prep_freshness !== "fresh" && data.prep_freshness !== "none" ? <p role="status" className="text-sm text-ink-secondary">{t(`today.brief.freshness.${data.prep_freshness}`)}</p> : null}
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
    </fieldset>
  );
}

function AgentNotes() {
  const channel = useChannel();
  const dismiss = useDismissChannel();
  const notes = (channel.data?.messages ?? []).filter((message) => message.kind !== "ask");
  if (!notes.length) return null;
  return (
    <Panel id="today-agents" icon="channel" title={t("channel.title")} count={notes.length} hint={t("today.agents.hint")}>
      <ul className="flex flex-col">
        {notes.map((message) => (
          <li key={message.id} data-testid="channel-message" className="flex flex-col gap-2 border-t border-line-subtle py-3">
            <p className="break-words text-md text-ink-primary">{message.text}</p>
            <p className="flex items-center gap-2 text-sm text-ink-muted">
              {message.agent}
              {message.count > 1 ? <span className="tabular-nums">{t("channel.times", { count: message.count })}</span> : null}
            </p>
            <span className="flex flex-wrap items-center gap-2">
              {message.thread ? <TextLink className="text-sm" href={`/mail/all/${message.thread}`}>{t("channel.openSource")}</TextLink> : null}
              <Button onClick={() => dismiss.mutate(message.id)}>{t("channel.dismiss")}</Button>
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/** What's overdue and what's due today, across tasks, reminders and deadlines from mail. */
function DueToday({ items }: { items: readonly DueItem[] }) {
  const formatDay = useDateOnly();
  const formatWhen = useDateTime();
  const tasks = useTasks(false);
  const saveTask = useSaveTask();
  const finish = (id: number) => {
    const task = tasks.data?.tasks.find((row) => row.id === id);
    if (task) saveTask.mutate({ id: task.id, title: task.title, notes: task.notes, status: "done", due: task.due ?? null, thread: task.thread ?? null, proposed: false });
  };
  const overdue = items.some((item) => item.overdue);
  return (
    <Panel id="today-due" icon="reminders" title={t("today.due")} count={items.length} urgent={overdue} {...(items.length ? { hint: t("today.due.hint") } : {})}>
      {items.length === 0 ? <p className="text-md text-ink-muted">{t("today.due.empty")}</p> : null}
      <ul className="flex flex-col">
        {items.map((item) => (
          <li key={`${item.kind}-${item.title}-${item.when}`} data-testid="due-item" className="flex flex-col gap-2 border-t border-line-subtle py-3">
            <Link href={item.link} className="focus-ring flex flex-col gap-px rounded-sm transition-colors duration-fast hover:text-accent-default">
              <span className="break-words text-md font-medium text-ink-primary">{item.title}</span>
              <span className={`text-sm tabular-nums ${item.overdue ? "font-medium text-status-danger" : "text-ink-secondary"}`}>
                {item.overdue ? t("today.due.overdue", { when: formatDay(item.when) }) : item.kind === "reminder" ? formatWhen(item.when) : t("today.due.today")}
              </span>
            </Link>
            {item.task_id ? <span><Button onClick={() => finish(item.task_id as number)}>{t("today.due.finish")}</Button></span> : null}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function SinceYouLooked() {
  const today = useToday();
  const assistant = useAssistant();
  const since = today.data?.since_last_look;
  if (!since?.mail && !since?.judged) return null;
  return (
    <section aria-label={t("today.since")} data-testid="since-last-look" className="flex flex-col gap-1 rounded-lg border border-line-subtle bg-surface-raised p-4 shadow-raised">
      <h2 className="text-lg font-medium text-ink-primary">{t("today.since")}</h2>
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
  const needed = useWaitingCount();
  const cockpit = useCockpit();
  const due = today.data?.due ?? [];
  return (
    <div className="today-container mx-auto flex max-w-page flex-col gap-6 p-6">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="font-serif text-display text-ink-primary">{greeting}</h1>
          {today.data ? <p data-testid="today-brief" className="text-md tabular-nums text-ink-secondary">{today.data.brief}</p> : null}
        </div>
        <nav aria-label={t("today.stat.label")} className="flex flex-wrap items-baseline divide-x divide-line-subtle">
          <Stat href="#today-needs" label={t("today.stat.needsYou")} value={needed} urgent />
          <Stat href="#today-due" label={t("today.stat.due")} value={due.length} alarming={due.some((item) => item.overdue)} urgent />
          <Stat href="#today-important" label={t("today.stat.important")} value={today.data?.needs_you.length ?? 0} urgent />
          <Stat href="/cockpit" label={t("today.stat.working")} value={cockpit.data?.jobs.length ?? 0} />
        </nav>
      </header>
      <MorningBrief />
      <FinishSetup />
      <MailOrganizationCard />
      {today.isError ? <ErrorState title={t("today.error")} onRetry={() => void today.refetch()} /> : null}
      {today.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {today.data && noMail ? <EmptyState icon="today" title={t("today.empty.title")} description={t("today.empty.description")} action={<TextLink href="/connectors">{t("mail.noAccount.action")}</TextLink>} /> : null}
      <div className="today-columns grid items-start gap-6">
        <div className="flex min-w-0 flex-col gap-6">
          <WaitingOnYou />
          {today.data && !noMail ? <ThreadList id="today-important" icon="priority" title={t("today.importantMail")} hint={t("today.important.hint")} urgent threads={today.data.needs_you} empty={t("today.needsYou.empty")} /> : null}
          {today.data?.follow_ups?.length ? <ThreadList chase icon="followUp" title={t("today.followUps")} threads={today.data.follow_ups} empty="" /> : null}
          {waitingOnOthers.length ? <ThreadList icon="sent" title={t("today.waiting")} threads={waitingOnOthers} empty="" /> : null}
        </div>
        <div className="flex min-w-0 flex-col gap-6">
          <DueToday items={due} />
          <AgentNotes />
          {today.data && !noMail ? <SinceYouLooked /> : null}
          {today.data?.automated_count ? <TextLink className="self-start text-md" href="/mail/all">{tn("today.automated", today.data.automated_count)}</TextLink> : null}
          <StatusLine />
        </div>
      </div>
    </div>
  );
}
