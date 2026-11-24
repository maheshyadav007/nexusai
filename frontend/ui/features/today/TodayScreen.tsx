"use client";

import { SortMailCard } from "./SortMailCard";
import Link from "next/link";
import appConfig from "@/app.config.json";
import { useEffect, useState, type ReactNode } from "react";
import type { BriefLine, BriefSections as Sections, ChannelMessage, DueItem, SourceRef, TodayThread, ToolApproval } from "@/ui/client/contracts.generated";
import { useDateOnly, useDateTime, useShortDate, useTimeOnly } from "@/ui/client/format";
import { useMailStatus, useSetImportance, useSetStatus } from "@/ui/client/mail";
import { groupApprovals, useApprovals, useDecideApprovals, useSessions } from "@/ui/client/sessions";
import { useLeadName } from "@/ui/client/home";
import { useProfile } from "@/ui/client/onboarding";
import { useChannel, useCockpit, useMattersBrief, useMatterList, useDismissChannel, useMarkTodaySeen, useReactToBrief, useReminders, useRemoveReminder, useRemoveTask, useRespondChannel, useSaveReminder, useSaveTask, useTasks, useToday, useWaitingCount, useAgentName } from "@/ui/client/work";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { ApprovalGroupCard, QuestionCard } from "@/ui/features/assistant/Cards";
import { Markdown } from "@/ui/features/assistant/Markdown";
import { MessageSources } from "@/ui/features/assistant/MessageSources";
import { useOpenSource } from "@/ui/features/sources/context";
import { fullHref, mailSource, type PreviewSource } from "@/ui/features/sources/kinds";
import { SourceChip } from "@/ui/features/sources/SourceChip";
import { Icon, type IconName } from "@/ui/icons";
import { AttentionCount } from "@/ui/primitives/AttentionCount";
import { Badge } from "@/ui/primitives/Badge";
import { DoneGroup, DoneRow } from "@/ui/primitives/DoneGroup";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Textarea } from "@/ui/primitives/Input";
import { CountPop, Presence, Rise } from "@/ui/primitives/Motion";
import { Popover } from "@/ui/primitives/Popover";
import { Pressable } from "@/ui/primitives/Pressable";
import { quickLook } from "@/ui/primitives/SourceRef";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { TextLink } from "@/ui/primitives/TextLink";
import { useToast } from "@/ui/primitives/Toast";
import { t, tn, type StringKey } from "@/ui/strings";
import { FinishSetup } from "./FinishSetup";
import { MatterGroups, useChangedMatters } from "./matters/BriefTab";
import { MattersTab } from "./matters/MattersTab";
import { useTodayView, type TodayView } from "./matters/parts";
import { WeekTab } from "./matters/WeekTab";
import { Tabs } from "@/ui/primitives/Tabs";

const MAIL_AGENT = "mail-agent";

/** A part of the day: what it is, how many, and what can be done about it, all at a glance. */
function Panel({ id, icon, title, count, urgent = false, hint, action, bare = false, children }: { id?: string; icon: IconName; title: string; count?: number; urgent?: boolean; hint?: string; action?: ReactNode; bare?: boolean; children: ReactNode }) {
  // Bare inside something that already draws the edge, like a popover.
  const frame = bare ? "" : `rounded-lg border bg-surface-raised p-4 shadow-raised ${urgent ? "border-accent-default" : "border-line-subtle"}`;
  return (
    <section id={id} aria-label={title} className={`flex scroll-mt-4 flex-col gap-3 ${frame}`}>
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
type Shown = Record<"decide" | "waiting" | "others" | "working" | "due", boolean>;
// Due starts hidden; every count can be ticked back on from Customize.
const SHOWN_AT_FIRST: Shown = { decide: true, waiting: true, others: true, working: true, due: false };

/** Which counts and panels Today shows. On this computer only: it's how the page looks to the
 *  person here, not a fact about their mail. Hidden ones are kept, never removed. */
function useTodayShown(): [Shown, (next: Shown) => void] {
  const [shown, setShown] = useState<Shown>(SHOWN_AT_FIRST);
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(appConfig.storageKeys.todayShown) ?? "{}") as Partial<Shown>;
      setShown({ ...SHOWN_AT_FIRST, ...saved });
    } catch {
      // Storage can be blocked or hold something else; the page then shows the usual counts.
    }
  }, []);
  const change = (next: Shown) => {
    setShown(next);
    try {
      localStorage.setItem(appConfig.storageKeys.todayShown, JSON.stringify(next));
    } catch {
      // Storage can be blocked; the choice then lasts until reload.
    }
  };
  return [shown, change];
}

function CustomizeToday({ shown, onChange }: { shown: Shown; onChange: (next: Shown) => void }) {
  const keys: (keyof Shown)[] = ["decide", "waiting", "others", "working", "due"];
  return (
    <Popover label={t("today.customize.title")} trigger={<Button variant="quiet" className="py-px text-sm">{t("today.customize")}</Button>}>
      <div className="flex flex-col gap-3">
        <p className="text-md font-medium text-ink-primary">{t("today.customize.title")}</p>
        {keys.map((key) => <Checkbox key={key} label={t(`today.customize.${key}` as StringKey)} checked={shown[key]} onChange={(on) => onChange({ ...shown, [key]: on })} />)}
        <p className="text-sm text-ink-muted">{t("today.customize.note")}</p>
      </div>
    </Popover>
  );
}

function Stat({ href, label, value, urgent = false, alarming = false }: { href: string; label: string; value: number; urgent?: boolean; alarming?: boolean }) {
  const tone = !value ? "text-ink-faint" : alarming ? "text-status-danger" : urgent ? "text-accent-default" : "text-ink-primary";
  return (
    <Link href={href} data-testid="today-stat" className="focus-ring group flex items-baseline gap-2 rounded-sm px-4 first:pl-0 last:pr-0">
      <CountPop value={value} className={`text-xl font-medium tabular-nums ${tone}`} />
      <span className="text-sm text-ink-secondary underline-offset-4 transition-colors duration-fast group-hover:text-ink-primary group-hover:underline">{label}</span>
    </Link>
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
        {message.source_ref ? <SourceChip source={message.source_ref} /> : null}
      </p>
      <QuestionCard question={message.text} options={message.options} multiple={message.multiple ?? false} pending={respond.isPending || dismiss.isPending} error={respond.error?.message ?? dismiss.error?.message ?? null} onAnswer={(answer) => respond.mutate({ id: message.id, answer })} onSkip={() => dismiss.mutate(message.id)} />
    </div>
  );
}

/** One thing waiting on the person, however it came to be, so it can be done alone or in bulk. */
// Past this many of one kind, they fold into one row: twenty memory notes read as one decision.
const GROUP_AT = 3;
// Up to this many suggestions show as they are; more fold into one line to open.
const SUGGESTIONS_SHOWN = 3;

/** Many proposals of one kind as one row: accept them all, or open the list to go one by one. */
function ProposalGroup({ testid, icon, title, accept, items, children }: { testid: string; icon: IconName; title: string; accept: string; items: readonly WaitingItem[]; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const acceptAll = async () => {
    setBusy(true);
    try {
      for (const item of items) if (item.doIt) await item.doIt();
    } finally {
      setBusy(false);
    }
  };
  return (
    <li data-testid={testid} className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        <Icon name={icon} className="h-4 w-4 shrink-0 text-ink-muted" />
        <span className="min-w-0 flex-1 text-md text-ink-primary">{title}</span>
        <Button variant="quiet" aria-expanded={open} onClick={() => setOpen(!open)}>{t(open ? "today.group.hide" : "today.group.review")}</Button>
        <Button loading={busy} onClick={() => void acceptAll()}>{accept}</Button>
      </div>
      {open ? <ul className="flex flex-col gap-3 border-l border-line-subtle pl-4">{children}</ul> : null}
    </li>
  );
}

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

function ProposalRow({ icon, title, meta, why, source, item, accept = t("tasks.accept"), decline = t("memory.decline"), kicker, matter, selecting, selected, onToggle }: { icon: IconName; title: string; meta: string; why?: string | null | undefined; source?: PreviewSource | null | undefined; item: WaitingItem; accept?: string; decline?: string; kicker?: string; matter?: MatterOf | undefined; selecting: boolean; selected: boolean; onToggle: () => void }) {
  const { acting, done, failed, run } = useRowAction(item);
  const lead = useLeadName();
  const { go } = useTodayView();
  const busy = acting !== null || done;
  return (
    <Rise as="li" settle data-testid="proposal" data-state={done ? "done" : failed ? "failed" : acting ? "running" : "idle"} className="ai-edge flex flex-col gap-2 rounded-lg p-4">
      <div className="flex items-start gap-3">
        {selecting ? <div className="mt-1 shrink-0"><Checkbox label={t("today.select.item", { title })} hideLabel checked={selected} onChange={onToggle} /></div> : null}
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface-sunken text-ink-secondary">
          <Icon name={icon} />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="text-sm text-ink-secondary">{kicker ?? t("tasks.proposed", { name: lead })}</p>
          <p className="break-words text-md font-medium text-ink-primary">{title}</p>
          <p className="text-sm tabular-nums text-ink-muted">{meta}</p>
          {why ? <p className="text-sm text-ink-secondary">{why}</p> : null}
          {source ? <div><SourceChip source={source} /></div> : null}
          {/* Which matter it's for, so a suggestion is never an orphan line. */}
          {matter ? <Pressable data-testid="proposal-matter" onClick={() => go("matters", matter.id)} className="focus-ring self-start rounded-sm text-sm text-accent-default underline underline-offset-2 hover:text-accent-hover">{t("today.proposal.for", { title: matter.title })}</Pressable> : null}
        </div>
        {selecting ? null : (
          <div className="flex shrink-0 items-center gap-2">
            {done ? (
              <span role="status" className="flex items-center gap-1 text-sm text-status-success"><Icon name="check" className="h-4 w-4" />{t("today.action.doneLabel")}</span>
            ) : (
              <>
                <Button variant="quiet" thinking loading={acting === "decline"} disabled={busy} onClick={() => void run("decline")}>{decline}</Button>
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
    <div data-testid="bulk-bar" className="sticky top-0 z-raised flex flex-wrap items-center gap-2 rounded-lg border border-line-subtle bg-surface-raised p-2 shadow-raised">
      <span role="status" className="px-2 text-sm tabular-nums text-ink-secondary">{chosen.length ? t("today.select.count", { count: chosen.length }) : t("today.select.none")}</span>
      <Button variant="quiet" disabled={busy} onClick={() => onPick(chosen.length === items.length ? [] : items.map((item) => item.key))}>{t("today.select.all")}</Button>
      <span className="flex-1" />
      <Button variant="quiet" disabled={busy} onClick={() => { onClear(); onCancel(); }}>{t("today.select.cancel")}</Button>
      <Button thinking loading={progress?.which === "decline"} disabled={busy || !chosen.length} onClick={() => void run("decline")}>{progress?.which === "decline" ? counting : t("today.select.decline", { count: chosen.length })}</Button>
      <Button variant="primary" thinking loading={progress?.which === "accept"} disabled={busy || !doable.length} onClick={() => void run("accept")}>{progress?.which === "accept" ? counting : t("today.select.doIt", { count: doable.length })}</Button>
    </div>
  );
}

/** Everything agents are waiting on the person for, in one place, answered right here. The
 *  same panel opens from the shield in the top bar, so both always agree. */
type MatterOf = { id: number; title: string };

/** Which matter each task or reminder belongs to, from the matters' own lists of their work. */
function useMatterOf(): (key: string) => MatterOf | undefined {
  const open = useMatterList(false);
  const brief = useMattersBrief();
  const found = new Map<string, MatterOf>();
  for (const matter of [...(open.data?.matters ?? []), ...(brief.data?.suggested ?? [])]) {
    for (const work of matter.work ?? []) found.set(`${work.kind}:${work.id}`, { id: matter.id, title: matter.title });
  }
  return (key) => found.get(key);
}

export function WaitingOnYou({ inPopover = false }: { inPopover?: boolean } = {}) {
  const lead = useLeadName();
  const channel = useChannel();
  const approvals = useApprovals();
  const tasks = useTasks(false);
  const reminders = useReminders();
  const matterOf = useMatterOf();
  const saveTask = useSaveTask();
  const removeTask = useRemoveTask();
  const saveReminder = useSaveReminder();
  const removeReminder = useRemoveReminder();
  const decideApprovals = useDecideApprovals();
  const dismiss = useDismissChannel();
  const formatWhen = useDateTime();
  const formatDay = useDateOnly();
  const asks = (channel.data?.messages ?? []).filter((message) => message.kind === "ask");
  const pending = approvals.data?.approvals ?? [];
  const proposedTasks = (tasks.data?.tasks ?? []).filter((task) => task.proposed);
  const proposedReminders = (reminders.data?.reminders ?? []).filter((reminder) => reminder.proposed);
  // A later email shows these done. The person closes them, or keeps them open.
  const doneTasks = (tasks.data?.tasks ?? []).filter((task) => task.looks_done && !task.proposed);
  const doneReminders = (reminders.data?.reminders ?? []).filter((reminder) => reminder.looks_done && !reminder.proposed);
  const count = useWaitingCount();
  const [selecting, setSelecting] = useState(false);
  // What only an agent can't settle (approvals, questions) shows first. Suggestions can wait, so
  // past a few they fold into one line: twelve memories and four folders read as one decision.
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const groups = groupApprovals(pending);
  const groupKey = (group: readonly ToolApproval[]) => `approval-${group[0]?.session}-${group[0]?.tool}`;
  const taskItem = (task: (typeof proposedTasks)[number]): WaitingItem => ({ key: `task-${task.id}`, title: task.title, doIt: () => saveTask.mutateAsync({ id: task.id, title: task.title, notes: task.notes, status: task.status, due: task.due ?? null, thread: task.thread ?? null, proposed: false }), decline: () => removeTask.mutateAsync(task.id) });
  const reminderItem = (reminder: (typeof proposedReminders)[number]): WaitingItem => ({ key: `reminder-${reminder.id}`, title: reminder.title, doIt: () => saveReminder.mutateAsync({ id: reminder.id, title: reminder.title, when: reminder.when, repeat: reminder.repeat, thread: reminder.thread ?? null, task: reminder.task ?? null, proposed: false }), decline: () => removeReminder.mutateAsync(reminder.id) });
  const doneTaskItem = (task: (typeof doneTasks)[number]): WaitingItem => ({ key: `done-task-${task.id}`, title: task.title, doIt: () => saveTask.mutateAsync({ id: task.id, title: task.title, notes: task.notes, status: "done", due: task.due ?? null, thread: task.thread ?? null, proposed: false }), decline: () => saveTask.mutateAsync({ id: task.id, title: task.title, notes: task.notes, status: task.status, due: task.due ?? null, thread: task.thread ?? null, proposed: false }) });
  const doneReminderItem = (reminder: (typeof doneReminders)[number]): WaitingItem => ({ key: `done-reminder-${reminder.id}`, title: reminder.title, doIt: () => removeReminder.mutateAsync(reminder.id), decline: () => saveReminder.mutateAsync({ id: reminder.id, title: reminder.title, when: reminder.when, repeat: reminder.repeat, thread: reminder.thread ?? null, task: reminder.task ?? null, proposed: false }) });
  const approvalItem = (group: readonly ToolApproval[]): WaitingItem => {
    const ids = group.map((row) => row.id);
    // Mail going out and commands running are read one at a time, never waved through in a batch.
    const careful = group.some((row) => row.preview?.kind === "mail" || row.preview?.kind === "command");
    return { key: groupKey(group), title: group[0]?.tool_label ?? group[0]?.tool ?? "", ...(careful ? {} : { doIt: () => decideApprovals.mutateAsync({ allow: ids }) }), decline: () => decideApprovals.mutateAsync({ deny: ids }) };
  };
  const askItem = (message: ChannelMessage): WaitingItem => ({ key: `ask-${message.id}`, title: message.text, decline: () => dismiss.mutateAsync(message.id) });
  const suggestionCount = proposedTasks.length + proposedReminders.length + doneTasks.length + doneReminders.length;
  const folded = !selecting && suggestionCount > SUGGESTIONS_SHOWN;
  const allItems: readonly WaitingItem[] = [
    ...groups.map(approvalItem),
    ...asks.map(askItem),
    ...proposedTasks.map(taskItem),
    ...proposedReminders.map(reminderItem),
    ...doneTasks.map(doneTaskItem),
    ...doneReminders.map(doneReminderItem),
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
  // Nothing waiting is said once, by the page, not by an empty panel.
  if (!channel.isSuccess || count === 0) return null;
  return (
    <Panel {...(inPopover ? { bare: true } : { id: "today-needs" })} icon="approvals" title={t(inPopover ? "waiting.title" : "today.needsYou")} count={count} urgent={count > 0} {...(count && !inPopover ? { hint: t("today.needsYou.hint") } : {})} action={inPopover ? <TextLink className="text-sm" href="/today#today-needs">{t("waiting.openToday")}</TextLink> : allItems.length > 1 && !selecting ? <Button variant="quiet" className="py-px" data-testid="bulk-select" onClick={() => setSelecting(true)}>{t("today.select")}</Button> : undefined}>
      {selecting ? (
        <>
          <BulkBar items={allItems} picked={picked} onPick={(keys) => setPicked(new Set(keys))} onClear={() => setPicked(new Set())} onCancel={() => { setSelecting(false); setPicked(new Set()); }} />
          {allItems.filter((item) => picked.has(item.key)).some((item) => !item.doIt) ? <p className="text-sm text-ink-muted">{t("today.select.review")}</p> : null}
        </>
      ) : null}
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
      {folded ? (
        <div data-testid="suggestions-fold" className="flex items-center gap-3 rounded-lg border border-line-subtle bg-surface-raised p-3">
          <Icon name="thinking" className="h-4 w-4 shrink-0 text-ink-muted" />
          <span className="min-w-0 flex-1 text-md text-ink-primary">{tn("today.suggestions.count", suggestionCount, { name: lead })}</span>
          <Button variant="quiet" aria-expanded={showSuggestions} onClick={() => setShowSuggestions(!showSuggestions)}>{t(showSuggestions ? "today.group.hide" : "today.group.review")}</Button>
        </div>
      ) : null}
      {folded && !showSuggestions ? null : <ul className="flex flex-col gap-3">
        <Presence>
          {(() => {
            const rows = proposedTasks.map((task) => {
              const item = taskItem(task);
              return <ProposalRow key={item.key} {...row(item)} icon="tasks" title={task.title} source={task.source_ref} matter={matterOf(`task:${task.id}`)} meta={task.due ? t("today.proposal.taskDue", { when: formatDay(task.due) }) : t("today.proposal.task")} />;
            });
            if (selecting || rows.length <= GROUP_AT) return rows;
            return (
              <ProposalGroup key="task-group" testid="proposal-group-tasks" icon="tasks" title={t("today.group.tasks", { count: rows.length, name: lead })} accept={t("today.group.addAll")} items={proposedTasks.map(taskItem)}>
                {rows}
              </ProposalGroup>
            );
          })()}
          {proposedReminders.map((reminder) => {
            const item = reminderItem(reminder);
            return <ProposalRow key={item.key} {...row(item)} icon="reminders" title={reminder.title} source={reminder.source_ref} matter={matterOf(`reminder:${reminder.id}`)} meta={t("today.proposal.reminder", { when: formatWhen(reminder.when) })} />;
          })}
          {doneTasks.map((task) => {
            const item = doneTaskItem(task);
            return <ProposalRow key={item.key} {...row(item)} icon="check" kicker={t("today.looksDone")} title={task.title} source={task.source_ref} matter={matterOf(`task:${task.id}`)} meta={task.due ? t("today.proposal.taskDue", { when: formatDay(task.due) }) : t("today.proposal.task")} why={task.looks_done} accept={t("today.looksDone.close")} decline={t("today.looksDone.keep")} />;
          })}
          {doneReminders.map((reminder) => {
            const item = doneReminderItem(reminder);
            return <ProposalRow key={item.key} {...row(item)} icon="check" kicker={t("today.looksDone")} title={reminder.title} source={reminder.source_ref} matter={matterOf(`reminder:${reminder.id}`)} meta={t("today.proposal.reminder", { when: formatWhen(reminder.when) })} why={reminder.looks_done} accept={t("today.looksDone.close")} decline={t("today.looksDone.keep")} />;
          })}
        </Presence>
      </ul>}
    </Panel>
  );
}

/** The brief laid out the same way every day: what matters most, then what's new and what's
 *  still open, one line per matter. */
function BriefSections({ sections, sources }: { sections: Sections; sources: SourceRef[] }) {
  const time = useTimeOnly();
  const part = (key: "new" | "open", lines: BriefLine[]) =>
    lines.length ? (
      <section aria-label={t(`today.brief.${key}`)} data-testid={`brief-${key}`} className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-ink-muted">{t(`today.brief.${key}`)}</h3>
        <ul className="flex flex-col gap-2">
          {lines.map((line, index) => (
            <li key={`${line.matter ?? "x"}-${index}`} data-testid="brief-line" className="flex gap-3">
              <span aria-hidden="true" className={`mt-2 h-2 w-2 shrink-0 rounded-full ${key === "new" ? "bg-accent-default" : "border border-line-strong"}`} />
              <div className="min-w-0 flex-1">
                <Markdown text={line.text} sources={sources} />
                {/* Kept in step during the day by the app; the morning run writes it afresh. */}
                {line.mark && line.at ? <span data-testid="brief-line-mark" className="text-sm font-medium text-accent-default">{t(`today.brief.${line.mark}`, { when: time(line.at) })}</span> : null}
              </div>
            </li>
          ))}
        </ul>
      </section>
    ) : null;
  return (
    <div className="flex flex-col gap-4">
      <div className="font-medium"><Markdown text={sections.lead} sources={sources} /></div>
      {part("new", sections.new ?? [])}
      {part("open", sections.open ?? [])}
    </div>
  );
}

/** Today's brief, first thing on the page, and how the next one gets better. */
function MorningBrief() {
  const today = useToday();
  const assistant = useAssistant();
  const react = useReactToBrief();
  const toast = useToast();
  const format = useDateTime();
  const time = useTimeOnly();
  const day = useShortDate();
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
        {data.prep_at ? (
          <span className="text-sm tabular-nums text-ink-muted">
            {t("today.brief.when", { when: format(data.prep_at) })}
            {data.prep_updated ? <span data-testid="brief-updated" className="font-medium text-accent-default"> · {t("today.brief.updatedAt", { when: time(data.prep_updated) })}</span> : null}
          </span>
        ) : null}
      </header>
      {data.prep_freshness && data.prep_freshness !== "fresh" && data.prep_freshness !== "none" ? <p role="status" className="text-sm text-ink-secondary">{t(`today.brief.freshness.${data.prep_freshness}`)}</p> : null}
      <div data-testid="today-prep" className="text-md text-ink-primary">
        {data.prep_sections ? <BriefSections sections={data.prep_sections} sources={data.prep_sources ?? []} /> : <Markdown text={data.prep_text} sources={data.prep_sources ?? []} />}
      </div>
      <DoneGroup label={t("today.brief.done")} count={data.prep_done?.length ?? 0} testid="brief-done">
        {(data.prep_done ?? []).map((item, index) => <DoneRow key={`${item.title}-${index}`} title={item.title} meta={[item.when ? day(item.when) : null, item.why || null].filter(Boolean).join(" · ")} />)}
      </DoneGroup>
      {data.prep_sources?.length ? <div><MessageSources sources={data.prep_sources} /></div> : null}
      <div className="flex flex-wrap items-center gap-1">
        <IconButton icon="like" label={t("today.brief.like")} aria-pressed={rating === "up"} data-testid="brief-like" className={rating === "up" ? "text-accent-default" : ""} disabled={react.isPending} onClick={() => rate("up")} />
        <IconButton icon="dislike" label={t("today.brief.dislike")} aria-pressed={rating === "down"} data-testid="brief-dislike" className={rating === "down" ? "text-accent-default" : ""} disabled={react.isPending} onClick={() => rate("down")} />
        <Button variant="quiet" aria-expanded={telling} data-testid="brief-tell" onClick={() => setTelling(!telling)}>{t("today.brief.tell")}</Button>
        <span className="flex-1" />
        {/* How fresh it is, quietly: what it was written from. */}
        {data.prep_at ? <span data-testid="brief-covers" className="text-sm tabular-nums text-ink-muted">{t("today.brief.covers", { when: time(data.prep_updated ?? data.prep_at) })}</span> : null}
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
  if (!items.length) return null;
  return (
    <Panel id="today-due" icon="reminders" title={t("today.due")} count={items.length} urgent={overdue} {...(items.length ? { hint: t("today.due.hint") } : {})}>
      <ul className="flex flex-col">
        {items.map((item) => (
          <li key={`${item.kind}-${item.title}-${item.when}`} data-testid="due-item" className="flex flex-col gap-2 border-t border-line-subtle py-3">
            <Link href={item.link} className="focus-ring flex flex-col gap-px rounded-sm transition-colors duration-fast hover:text-accent-default">
              <span className="break-words text-md font-medium text-ink-primary">{item.title}</span>
              <span className={`text-sm tabular-nums ${item.overdue ? "font-medium text-status-danger" : "text-ink-secondary"}`}>
                {item.overdue ? t("today.due.overdue", { when: formatDay(item.when) }) : item.kind === "reminder" ? formatWhen(item.when) : t("today.due.today")}
              </span>
            </Link>
            {item.source_ref || item.task_id ? (
              <span className="flex flex-wrap items-center gap-2">
                {item.source_ref ? <SourceChip source={item.source_ref} /> : null}
                {item.task_id ? <Button onClick={() => finish(item.task_id as number)}>{t("today.due.finish")}</Button> : null}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function SinceYouLooked() {
  const mailAgent = useAgentName()("mail");
  const today = useToday();
  const assistant = useAssistant();
  const since = today.data?.since_last_look;
  const changed = useChangedMatters().size;
  if (!since?.mail && !since?.judged && !changed) return null;
  return (
    <section aria-label={t("today.since")} data-testid="since-last-look" className="flex flex-col gap-1 rounded-lg border border-line-subtle bg-surface-raised p-4 shadow-raised">
      <h2 className="text-lg font-medium text-ink-primary">{t("today.since")}</h2>
      {since?.mail || since?.judged ? <p className="text-md tabular-nums text-ink-secondary">{t("today.since.counts", { mail: since.mail ?? 0, important: since.important ?? 0, filed: since.filed ?? 0 })}</p> : null}
      {since?.proposed ? <p className="text-md tabular-nums text-ink-secondary">{tn("today.since.proposed", since.proposed, { agent: mailAgent })}</p> : null}
      {changed ? <TextLink href="#today-important" data-testid="since-changed" className="self-start text-md">{tn("today.since.changed", changed)}</TextLink> : null}
      <Pressable onClick={() => assistant.openSession(MAIL_AGENT)} className="self-start rounded-sm text-sm text-ink-secondary underline underline-offset-2 hover:text-ink-primary">{t("today.since.open", { agent: mailAgent })}</Pressable>
    </section>
  );
}

/** Today stays about the person's day: the app speaks here only when something of its own
 *  stopped working and needs them, with the way to fix it. Everything else is in the Cockpit. */
function ProblemLine() {
  const cockpit = useCockpit();
  const problems = (cockpit.data?.health ?? []).filter((item) => item.state === "problem");
  if (!problems.length) return null;
  return (
    <div className="flex flex-col gap-2">
      {problems.map((item) => (
        <p key={item.id} role="alert" data-testid="today-problem" className="flex flex-wrap items-center gap-3 rounded-lg border border-status-danger/30 bg-status-danger/10 px-4 py-3 text-md text-status-danger">
          <Icon name="error" className="h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1">{t("today.problem", { what: item.label, detail: item.detail })}</span>
          <Link href={item.link ?? "/cockpit"} className="focus-ring rounded-sm font-medium text-status-danger underline underline-offset-2">{t("today.problem.fix")}</Link>
        </p>
      ))}
    </div>
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
  const needed = useWaitingCount();
  const [shown, setShown] = useTodayShown();
  const cockpit = useCockpit();
  const due = today.data?.due ?? [];
  const { view, go } = useTodayView();
  const matters = useMattersBrief();
  const open = matters.data ? matters.data.needs_you.length + matters.data.waiting.length + matters.data.fyi.length : null;
  const clear = Boolean(today.data) && !noMail && needed === 0 && due.length === 0 && open === 0 && !today.data?.needs_you.length;
  const brief = (
    <div className="flex flex-col gap-6">
      <MorningBrief />
      <FinishSetup />
      {today.isError ? <ErrorState title={t("today.error")} onRetry={() => void today.refetch()} /> : null}
      {today.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {today.data && noMail ? <EmptyState icon="today" title={t("today.empty.title")} description={t("today.empty.description")} action={<TextLink href="/connectors?connector=email">{t("mail.noAccount.action")}</TextLink>} /> : null}
      {clear ? <p data-testid="today-clear" className="flex items-center gap-2 text-md text-ink-secondary"><Icon name="check" className="h-4 w-4 text-status-success" />{t("today.clear")}</p> : null}
      <div className="today-columns grid items-start gap-6">
        <div className="flex min-w-0 flex-col gap-6">
          <WaitingOnYou />
          {today.data && !noMail ? <MatterGroups /> : null}
        </div>
        <div className="flex min-w-0 flex-col gap-6">
          {shown.due ? <DueToday items={due} /> : null}
          {today.data && !noMail ? <SinceYouLooked /> : null}
        </div>
      </div>
    </div>
  );
  return (
    <div className="today-container mx-auto flex max-w-page flex-col gap-6 p-6">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="font-serif text-display text-ink-primary">{greeting}</h1>
          {today.data ? <p data-testid="today-brief" className="text-md tabular-nums text-ink-secondary">{today.data.brief}</p> : null}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <nav aria-label={t("today.stat.label")} className="flex flex-wrap items-baseline divide-x divide-line-subtle">
            {shown.decide ? <Stat href="#today-needs" label={t("today.stat.needsYou")} value={needed} urgent /> : null}
            {/* Matters, so a conversation of seven emails counts once. */}
            {shown.waiting ? <Stat href="#today-important" label={t("today.stat.important")} value={matters.data?.needs_you.length ?? 0} urgent /> : null}
            {shown.others ? <Stat href="#today-waiting" label={t("today.stat.others")} value={matters.data?.waiting.length ?? 0} /> : null}
            {shown.working ? <Stat href="/cockpit" label={t("today.stat.working")} value={cockpit.data?.jobs.length ?? 0} /> : null}
            {shown.due ? <Stat href="#today-due" label={t("today.stat.due")} value={due.length} alarming={due.some((item) => item.overdue)} urgent /> : null}
          </nav>
          <CustomizeToday shown={shown} onChange={setShown} />
        </div>
      </header>
      <ProblemLine />
      {/* Until it's sorted the AI reads nothing, so this comes before everything else. */}
      <SortMailCard />
      <Tabs
        label={t("matters.tabs")}
        value={view}
        onValueChange={(next) => go(next as TodayView)}
        tabs={[
          { value: "brief", label: t("matters.tab.brief"), content: brief },
          { value: "week", label: t("matters.tab.week"), content: <WeekTab /> },
          { value: "matters", label: t("matters.tab.matters"), content: <MattersTab /> },
        ]}
      />
    </div>
  );
}
