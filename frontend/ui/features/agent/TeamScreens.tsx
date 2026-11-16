"use client";

import { useState } from "react";
import type { AgentCard, TeamTask } from "@/ui/client/contracts.generated";
import { useRelativeTime } from "@/ui/client/format";
import { useAgentCards, useAgentName, useCancelTask, useNoteOnTask, useRenameAgent, useResetAgentName, useRetryTask, useSetMascot, useTeamTask, useTeamTasks } from "@/ui/client/work";
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
import { t, type StringKey } from "@/ui/strings";

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

function ProfileCard({ card }: { card: AgentCard }) {
  const name = useAgentName();
  const assistant = useAssistant();
  const mascot = useSetMascot();
  const relative = useRelativeTime();
  const usage = { tokens_today: 0, tokens_week: 0, tokens_usual_day: 0, messages_today: 0, tasks_verified: 0, tasks_rejected: 0, tasks_blocked: 0, ...card.usage };
  const now = card.now ?? { state: "idle" as const };
  const gives = card.may_assign_to.map((id) => name(id)).filter(Boolean);
  const talkable = card.accepts.includes("person");
  return (
    <li data-testid="agent-card" data-agent={card.id} className="flex flex-col gap-4 rounded-lg border border-line-subtle bg-surface-raised p-4 shadow-raised">
      <div className="flex items-start gap-4">
        <Mascot seed={card.mascot.seed} shape={card.mascot.style} name={card.name} size="lg" />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h3 className="flex flex-wrap items-baseline gap-2 text-lg font-medium text-ink-primary">
            {card.name}
            <span className="text-sm font-normal text-ink-muted">@{card.handle}</span>
            {card.default ? <Badge tone="accent">{t("team.default")}</Badge> : null}
            {card.kind === "yours" ? <Badge>{t("team.yours")}</Badge> : null}
          </h3>
          <p className="text-md text-ink-secondary">{card.role}</p>
          <p data-testid="agent-now" data-state={now.state} className="flex items-center gap-2 text-sm text-ink-primary">
            <StatusDot tone={NOW_TONE[now.state]} />
            {nowLine(card, name)}
            {now.since && now.state !== "idle" ? <span className="text-ink-muted">· {relative(now.since)}</span> : null}
          </p>
        </div>
      </div>
      <dl className="grid grid-cols-3 gap-2 border-y border-line-subtle py-3">
        {([
          ["team.usage.today", usage.tokens_today],
          ["team.usage.week", usage.tokens_week],
          ["team.usage.messages", usage.messages_today],
        ] as const).map(([label, value]) => (
          <div key={label} className="flex flex-col gap-px">
            <dt className="text-sm text-ink-muted">{t(label)}</dt>
            <dd className="text-lg tabular-nums text-ink-primary">{value.toLocaleString()}</dd>
            {label === "team.usage.today" && usage.tokens_usual_day ? <dd className="text-sm tabular-nums text-ink-muted">{t("team.usage.usual", { count: usage.tokens_usual_day.toLocaleString() })}</dd> : null}
          </div>
        ))}
      </dl>
      <p className="text-sm text-ink-secondary">
        {t("team.usage.recordLine", { verified: usage.tasks_verified, rejected: usage.tasks_rejected, blocked: usage.tasks_blocked })}
        {" · "}
        {gives.length ? t("team.givesTo", { agents: gives.join(", ") }) : t("team.givesNone")}
      </p>
      {card.can_do.length ? (
        <ul aria-label={t("team.canDo", { agent: card.name })} className="flex flex-col gap-1 text-sm text-ink-secondary">
          {card.can_do.map((line) => <li key={line}>{line}</li>)}
        </ul>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {talkable ? <Button variant="secondary" onClick={() => (card.default ? assistant.newChat() : assistant.talkTo(card.handle))}>{t("team.talk", { agent: card.name })}</Button> : <span className="text-sm text-ink-muted">{t("team.ownChatOnly")}</span>}
        <RenameDialog card={card} />
        <Button variant="quiet" loading={mascot.isPending} onClick={() => mascot.mutate({ id: card.id, seed: freshSeed() })}>{t("team.newFace")}</Button>
      </div>
    </li>
  );
}

export function TeamCards() {
  const cards = useAgentCards();
  const rows = cards.data?.cards ?? [];
  if (cards.isPending) return <Skeleton className="h-6 w-full" />;
  if (cards.isError) return <ErrorState title={t("team.error")} onRetry={() => void cards.refetch()} />;
  return (
    <div className="flex flex-col gap-3">
      {/* Each card's name is an h3, so the list needs its h2 for screen-reader navigation. */}
      <h2 className="sr-only">{t("team.title")}</h2>
      <p className="text-md text-ink-secondary">{t("team.description")}</p>
      <ul aria-label={t("team.title")} className="grid gap-3 xl:grid-cols-2">
        {rows.map((card) => <ProfileCard key={card.id} card={card} />)}
      </ul>
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
