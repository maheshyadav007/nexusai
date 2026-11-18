"use client";

import NextLink from "next/link";
import { useState } from "react";
import type { AgentCard, TeamTask } from "@/ui/client/contracts.generated";
import { useDateTime, useRelativeTime } from "@/ui/client/format";
import { useAgentCards, useAgentName, useSchedules, useCancelTask, useNoteOnTask, useRenameAgent, useResetAgentName, useRetryTask, useSetMascot, useTeamTask, useTeamTasks } from "@/ui/client/work";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Mascot } from "@/ui/primitives/Mascot";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { LiveDot } from "@/ui/primitives/LiveDot";
import { Pressable } from "@/ui/primitives/Pressable";
import { TextLink } from "@/ui/primitives/TextLink";
import { Icon } from "@/ui/icons";
import { t, tn, type StringKey } from "@/ui/strings";

const NOW_TONE = { idle: "idle", working: "running", waiting: "waiting", blocked: "failed", off: "idle" } as const;
const TASK_TONE: Readonly<Record<string, "neutral" | "accent" | "success" | "warning" | "danger">> = {
  queued: "neutral",
  working: "accent",
  input_required: "warning",
  blocked: "danger",
  reported: "warning",
  verified: "success",
  rejected: "danger",
  failed: "danger",
  canceled: "neutral",
};
const OPEN = new Set(["queued", "working", "input_required", "blocked", "reported"]);

function nowLine(card: AgentCard, name: (id: string) => string): string {
  const now = card.now ?? { state: "idle" };
  if (now.state === "working") return now.task_id ? t("team.now.workingOn", { task: now.task_id }) : t("team.now.working");
  if (now.state === "waiting") return t("team.now.waitingOn", { agent: name(now.waiting_on ?? "") || t("team.person"), task: now.task_id ?? "" });
  if (now.state === "blocked") return t("team.now.blocked", { task: now.task_id ?? "", reason: now.reason ?? "" });
  return t(`team.now.${now.state}` as StringKey);
}

/** A fresh face for an agent: a new seed, kept until the person asks again. */
const freshSeed = () => Math.random().toString(36).slice(2, 10);

function RenameDialog({ card }: { card: AgentCard }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(card.name);
  const [handle, setHandle] = useState(card.handle);
  const rename = useRenameAgent();
  const reset = useResetAgentName();
  const failure = (rename.error ?? reset.error)?.message;
  return (
    <Dialog
      title={t("team.rename.title", { agent: card.name })}
      description={t("team.rename.description")}
      open={open}
      onOpenChange={(next) => { setOpen(next); if (next) { setName(card.name); setHandle(card.handle); rename.reset(); reset.reset(); } }}
      trigger={<Button variant="quiet">{t("team.rename")}</Button>}
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          // The promise settles even when the card re-renders with its new name, so the dialog closes.
          rename.mutateAsync({ id: card.id, name, handle: handle.replace(/^@/, "").toLowerCase() }).then(() => setOpen(false), () => undefined);
        }}
      >
        <Field label={t("team.rename.name")}>{(control) => <Input {...control} value={name} onChange={(event) => setName(event.target.value)} maxLength={40} />}</Field>
        <Field label={t("team.rename.handle")} hint={t("team.rename.handleHint")} {...(failure ? { error: failure } : {})}>
          {(control) => <Input {...control} value={handle} onChange={(event) => setHandle(event.target.value)} maxLength={24} />}
        </Field>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {card.renamed && card.kind !== "yours" ? <Button type="button" variant="quiet" loading={reset.isPending} onClick={() => void reset.mutateAsync({ id: card.id }).then(() => setOpen(false), () => undefined)}>{t("team.rename.reset")}</Button> : null}
          <Button type="submit" variant="primary" loading={rename.isPending} disabled={!name.trim() || !handle.trim()}>{t("team.rename.save")}</Button>
        </div>
      </form>
    </Dialog>
  );
}

const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
const usageOf = (card: AgentCard) => ({ tokens_today: 0, tokens_week: 0, tokens_usual_day: 0, messages_today: 0, tasks_verified: 0, tasks_rejected: 0, tasks_blocked: 0, ...card.usage });

/** What the agent is doing now, with the live signal when it's really working. */
function NowLine({ card }: { card: AgentCard }) {
  const name = useAgentName();
  const relative = useRelativeTime();
  const now = card.now ?? { state: "idle" as const };
  return (
    <span data-testid="agent-now" data-state={now.state} className="flex min-w-0 items-center gap-2 text-sm text-ink-muted">
      {now.state === "working" ? <LiveDot /> : now.state === "waiting" ? <LiveDot tone="waiting" /> : <StatusDot tone={NOW_TONE[now.state]} />}
      <span className="min-w-0 truncate">{nowLine(card, name)}{now.since && now.state !== "idle" ? ` · ${relative(now.since)}` : ""}</span>
    </span>
  );
}

function talk(card: AgentCard, assistant: ReturnType<typeof useAssistant>) {
  if (card.default) assistant.newChat();
  else assistant.talkTo(card.handle);
}

/** One agent at a glance: who it is, what it's doing, and one way to talk to it. The rest opens beside. */
function ProfileCard({ card, selected, onSelect }: { card: AgentCard; selected: boolean; onSelect: () => void }) {
  const assistant = useAssistant();
  const usage = usageOf(card);
  const talkable = card.accepts.includes("person");
  return (
    <li data-testid="agent-card" data-agent={card.id} className={`flex flex-col overflow-hidden rounded-lg border bg-surface-raised transition-colors duration-fast ${selected ? "border-accent-default" : "border-line-subtle hover:border-line-strong"}`}>
      <Pressable aria-pressed={selected} onClick={onSelect} className="focus-ring flex flex-1 flex-col gap-3 rounded-lg p-4 text-left">
        <span className="flex items-center gap-3">
          <Mascot seed={card.mascot.seed} shape={card.mascot.style} name={card.name} size="md" />
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="flex min-w-0 items-baseline gap-2">
              <span className="truncate text-lg font-medium text-ink-primary">{card.name}</span>
              <span className="shrink-0 text-sm text-ink-muted">@{card.handle}</span>
            </span>
            <NowLine card={card} />
          </span>
          {card.default ? <Badge tone="accent">{t("team.default")}</Badge> : card.kind === "yours" ? <Badge>{t("team.yours")}</Badge> : null}
        </span>
        <span className="line-clamp-2 text-md text-ink-secondary">{card.role}</span>
      </Pressable>
      <div className="flex items-center gap-3 border-t border-line-subtle py-2 pl-4 pr-2 text-sm text-ink-muted">
        {/* One line at any width: the numbers give way, Talk keeps its place. */}
        <span className="flex min-w-0 flex-1 items-center gap-3 truncate">
          <span className="truncate"><strong className="font-medium tabular-nums text-ink-primary">{compact.format(usage.tokens_today)}</strong> {t("team.card.tokens")}</span>
          <span className="shrink-0"><strong className="font-medium tabular-nums text-ink-primary">{usage.tasks_verified}</strong> {t("team.card.tasks")}</span>
        </span>
        {talkable ? <Button variant="quiet" aria-label={t("team.talk", { agent: card.name })} onClick={() => talk(card, assistant)}><Icon name="chat" className="h-4 w-4" />{t("team.card.talk")}</Button> : <span className="min-w-0 truncate text-ink-muted">{t("team.ownChatOnly")}</span>}
      </div>
    </li>
  );
}

/** Everything about the chosen agent, beside the cards, so the cards themselves stay calm. */
function AgentDetail({ card }: { card: AgentCard }) {
  const name = useAgentName();
  const assistant = useAssistant();
  const mascot = useSetMascot();
  const usage = usageOf(card);
  // The person's schedules are one card on the team, so they're one entry here too.
  const yours = new Set((useAgentCards().data?.cards ?? []).filter((item) => item.kind === "yours").map((item) => item.id));
  const scheduled = card.may_assign_to.filter((id) => yours.has(id)).length;
  const gives = [...card.may_assign_to.filter((id) => !yours.has(id)).map((id) => name(id)).filter(Boolean), ...(scheduled ? [tn("team.schedules.count", scheduled)] : [])];
  const talkable = card.accepts.includes("person");
  return (
    <aside aria-label={t("team.detail", { agent: card.name })} data-testid="agent-detail" className="flex flex-col gap-5 rounded-lg border border-line-subtle bg-surface-raised p-5">
      <div className="flex items-center gap-4">
        <Mascot seed={card.mascot.seed} shape={card.mascot.style} name={card.name} size="lg" />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h3 className="truncate text-xl font-medium text-ink-primary">{card.name}</h3>
          <span className="text-sm text-ink-muted">@{card.handle}</span>
          <NowLine card={card} />
        </div>
      </div>
      <p className="text-md text-ink-secondary">{card.role}</p>
      <div className="flex flex-wrap items-center gap-2">
        {talkable ? <Button variant="primary" onClick={() => talk(card, assistant)}><Icon name="chat" className="h-4 w-4" />{t("team.talk", { agent: card.name })}</Button> : null}
        <RenameDialog card={card} />
        <Button variant="quiet" loading={mascot.isPending} onClick={() => mascot.mutate({ id: card.id, seed: freshSeed() })}>{t("team.newFace")}</Button>
      </div>
      <dl className="grid grid-cols-3 gap-2">
        {([
          ["team.usage.today", usage.tokens_today],
          ["team.usage.week", usage.tokens_week],
          ["team.usage.messages", usage.messages_today],
        ] as const).map(([label, value]) => (
          <div key={label} className="flex flex-col gap-1 rounded-md bg-surface-sunken px-3 py-2">
            <dt className="text-sm text-ink-muted">{t(label)}</dt>
            <dd className="text-lg tabular-nums text-ink-primary">{compact.format(value)}</dd>
          </div>
        ))}
      </dl>
      {card.can_do.length ? (
        <section className="flex flex-col gap-2">
          <h4 className="text-sm font-medium text-ink-muted">{t("team.whatItDoes")}</h4>
          <ul aria-label={t("team.canDo", { agent: card.name })} className="flex list-disc flex-col gap-1 pl-5 text-md text-ink-secondary">
            {card.can_do.map((line) => <li key={line}>{line}</li>)}
          </ul>
        </section>
      ) : null}
      <section className="flex flex-col gap-2">
        <h4 className="text-sm font-medium text-ink-muted">{t("team.work")}</h4>
        <p className="text-md text-ink-secondary">{t("team.usage.recordLine", { verified: usage.tasks_verified, rejected: usage.tasks_rejected, blocked: usage.tasks_blocked })}</p>
        <p className="text-md text-ink-secondary">{gives.length ? t("team.givesTo", { agents: gives.join(", ") }) : t("team.givesNone")}</p>
        {usage.tokens_usual_day ? <p className="text-sm text-ink-muted">{t("team.usage.usual", { count: usage.tokens_usual_day.toLocaleString() })}</p> : null}
      </section>
      <TextLink href="/agent/channel?tab=runs">{t("team.seeRuns")}</TextLink>
    </aside>
  );
}

/** Every schedule the person made runs as an agent of its own. Here they're one card, so the
 * team stays the team however many there are. */
function SchedulesCard({ count }: { count: number }) {
  const schedules = useSchedules();
  const format = useDateTime();
  const next = (schedules.data?.schedules ?? []).flatMap((row) => (row.kind === "prompt" && row.enabled !== false && row.next_run ? [row.next_run] : [])).sort()[0];
  return (
    <li data-testid="schedules-card" className="flex flex-col overflow-hidden rounded-lg border border-line-subtle bg-surface-raised transition-colors duration-fast hover:border-line-strong">
      <NextLink href="/agent/schedules" className="focus-ring flex flex-1 flex-col gap-3 rounded-lg p-4 text-left">
        <span className="flex items-center gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-surface-sunken text-ink-muted"><Icon name="schedules" className="h-5 w-5" /></span>
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="truncate text-lg font-medium text-ink-primary">{t("team.schedules.title")}</span>
            <span className="truncate text-sm tabular-nums text-ink-muted">{next ? tn("team.schedules.countNext", count, { when: format(next) }) : tn("team.schedules.count", count)}</span>
          </span>
        </span>
        <span className="line-clamp-2 text-md text-ink-secondary">{t("team.schedules.role")}</span>
      </NextLink>
    </li>
  );
}

export function TeamCards() {
  const cards = useAgentCards();
  const all = cards.data?.cards ?? [];
  const rows = all.filter((card) => card.kind !== "yours");
  const yours = all.length - rows.length;
  const [chosen, setChosen] = useState<string | null>(null);
  if (cards.isPending) return <Skeleton className="h-6 w-full" />;
  if (cards.isError) return <ErrorState title={t("team.error")} onRetry={() => void cards.refetch()} />;
  const selected = rows.find((card) => card.id === chosen) ?? rows.find((card) => card.default) ?? rows[0];
  const working = rows.filter((card) => card.now?.state === "working").length;
  return (
    <div className="flex flex-col gap-4">
      {/* Each card's name is in a button, so the list needs its h2 for screen-reader navigation. */}
      <h2 className="sr-only">{t("team.title")}</h2>
      <p className="text-md text-ink-muted">{t("team.summary", { count: rows.length, working, lead: rows.find((card) => card.default)?.name ?? "" })}</p>
      <div className="team-container">
      <div className="team-layout">
        <ul aria-label={t("team.title")} className="team-cards grid min-w-0 gap-3">
          {rows.map((card) => <ProfileCard key={card.id} card={card} selected={card.id === selected?.id} onSelect={() => setChosen(card.id)} />)}
          {yours ? <SchedulesCard count={yours} /> : null}
        </ul>
        {selected ? <AgentDetail card={selected} /> : null}
      </div>
      </div>
    </div>
  );
}

function TaskDetail({ task }: { task: TeamTask }) {
  const view = useTeamTask(task.id);
  const name = useAgentName();
  const note = useNoteOnTask();
  const cancel = useCancelTask();
  const retry = useRetryTask();
  const relative = useRelativeTime();
  const [text, setText] = useState("");
  const who = (id: string) => (id === "person" ? t("team.person") : name(id));
  const shown = view.data?.task ?? task;
  return (
    <div className="flex flex-col gap-3 text-sm">
      <dl className="grid grid-cols-1 gap-1 md:grid-cols-4">
        <dt className="text-ink-muted">{t("team.task.expected")}</dt>
        <dd className="text-ink-primary md:col-span-3">{shown.expected_output}</dd>
        <dt className="text-ink-muted">{t("team.task.done")}</dt>
        <dd className="text-ink-primary md:col-span-3">{shown.done_criteria}</dd>
        {shown.references.length ? <><dt className="text-ink-muted">{t("team.task.references")}</dt><dd className="text-ink-primary md:col-span-3">{shown.references.join(", ")}</dd></> : null}
        <dt className="text-ink-muted">{t("team.task.budget")}</dt>
        <dd className="tabular-nums text-ink-primary md:col-span-3">{t("team.task.budgetValue", { used: (shown.tokens_used ?? 0).toLocaleString(), budget: shown.budget_tokens.toLocaleString() })}</dd>
        {shown.outcome ? <><dt className="text-ink-muted">{t("team.task.outcome")}</dt><dd className="break-words text-ink-primary md:col-span-3">{shown.outcome}</dd></> : null}
        {shown.evidence?.length ? <><dt className="text-ink-muted">{t("team.task.evidence")}</dt><dd className="text-ink-primary md:col-span-3">{shown.evidence.join(", ")}</dd></> : null}
        {shown.failure ? <><dt className="text-ink-muted">{t("team.task.why")}</dt><dd className="text-status-danger md:col-span-3">{t(`team.failure.${shown.failure}` as StringKey)}</dd></> : null}
      </dl>
      {view.data?.messages.length ? (
        <ol aria-label={t("team.task.thread")} className="flex flex-col gap-2 border-l border-line-subtle pl-3">
          {view.data.messages.map((message) => (
            <li key={message.id} className="flex flex-col gap-px">
              <span className="flex flex-wrap items-center gap-2 text-ink-muted">
                <span className="font-medium text-ink-secondary">{who(message.sender)}</span>
                <Badge>{t(`team.kind.${message.kind}` as StringKey)}</Badge>
                <span className="tabular-nums">{relative(message.time)}</span>
                {message.untrusted ? <Badge tone="warning">{t("agentChannel.untrusted")}</Badge> : null}
              </span>
              <p className="break-words text-ink-primary">{message.text}</p>
            </li>
          ))}
        </ol>
      ) : null}
      {OPEN.has(shown.state) ? (
        <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); note.mutate({ id: task.id, text }, { onSuccess: () => setText("") }); }}>
          <div className="min-w-0 flex-1">
            <Field label={t("team.task.note", { agent: name(shown.owner) })}>{(control) => <Input {...control} value={text} onChange={(event) => setText(event.target.value)} maxLength={2000} />}</Field>
          </div>
          <Button type="submit" loading={note.isPending} disabled={!text.trim()}>{t("team.task.send")}</Button>
        </form>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {["blocked", "failed", "rejected"].includes(shown.state) ? <Button loading={retry.isPending} onClick={() => retry.mutate({ id: task.id })}>{t("team.task.retry")}</Button> : null}
        {OPEN.has(shown.state) ? <Button variant="danger" loading={cancel.isPending} onClick={() => cancel.mutate({ id: task.id })}>{t("team.task.cancel")}</Button> : null}
      </div>
    </div>
  );
}

export function TeamTasks() {
  const [openOnly, setOpenOnly] = useState(true);
  const tasks = useTeamTasks(openOnly);
  const name = useAgentName();
  const rows = tasks.data?.tasks ?? [];
  const who = (id: string) => (id === "person" ? t("team.person") : name(id));
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-md text-ink-secondary">{t("team.tasks.description")}</p>
        <Button variant="quiet" onClick={() => setOpenOnly(!openOnly)}>{t(openOnly ? "team.tasks.showAll" : "team.tasks.showOpen")}</Button>
      </div>
      {tasks.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {tasks.isError ? <ErrorState title={t("team.tasks.error")} onRetry={() => void tasks.refetch()} /> : null}
      {tasks.isSuccess && rows.length === 0 ? <EmptyState icon="channel" title={t(openOnly ? "team.tasks.emptyOpen" : "team.tasks.empty")} /> : null}
      <ul aria-label={t("team.tasks.title")} className="flex flex-col gap-2">
        {rows.map((task) => (
          <li key={task.id} data-testid="team-task" data-state={task.state}>
            <ExpandRow
              label={t("team.tasks.open", { task: task.id })}
              title={t("team.tasks.row", { task: task.id, objective: task.objective })}
              meta={t("team.tasks.who", { from: who(task.assigner), to: who(task.owner) })}
              aside={<Badge tone={TASK_TONE[task.state] ?? "neutral"}>{t(`team.state.${task.state}` as StringKey)}</Badge>}
            >
              <TaskDetail task={task} />
            </ExpandRow>
          </li>
        ))}
      </ul>
    </div>
  );
}
