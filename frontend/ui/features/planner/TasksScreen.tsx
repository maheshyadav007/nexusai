"use client";

import { useEffect, useState } from "react";
import type { Task } from "@/ui/client/contracts.generated";
import { useDateOnly, useRelativeTime, useShortDate } from "@/ui/client/format";
import { AddBar, DuePicker } from "./AddBar";
import { useAgentName, useRemoveTask, useSaveTask, useTasks } from "@/ui/client/work";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { Icon } from "@/ui/icons";
import { useLeadName } from "@/ui/client/home";
import { RoundCheck, SuggestedCheck } from "@/ui/primitives/Checkbox";
import { Button } from "@/ui/primitives/Button";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { DoneGroup, DoneRow } from "@/ui/primitives/DoneGroup";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { ListGroup, MetaDot } from "@/ui/primitives/List";
import { PageHeader } from "@/ui/primitives/PageHeader";
import { Segmented } from "@/ui/primitives/Segmented";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t, tn, type StringKey } from "@/ui/strings";
import { SourceChip } from "@/ui/features/sources/SourceChip";

const STATUSES = [
  { value: "todo", label: t("tasks.status.todo") },
  { value: "in_progress", label: t("tasks.status.inProgress") },
  { value: "done", label: t("tasks.status.done") },
];

type View = "open" | "suggested";

const fields = (task: Task) => ({ id: task.id, title: task.title, notes: task.notes, status: task.status, due: task.due ?? null, thread: task.thread ?? null, proposed: task.proposed });

const today = () => new Date().toLocaleDateString("sv-SE");
const inDays = (days: number) => { const date = new Date(); date.setDate(date.getDate() + days); return date.toLocaleDateString("sv-SE"); };

function bucket(task: Task): StringKey {
  if (!task.due) return "tasks.group.noDate";
  if (task.due < today()) return "tasks.group.overdue";
  if (task.due === today()) return "tasks.group.today";
  if (task.due <= inDays(7)) return "tasks.group.week";
  return "tasks.group.later";
}
const ORDER: readonly StringKey[] = ["tasks.group.overdue", "tasks.group.today", "tasks.group.week", "tasks.group.later", "tasks.group.noDate"];

function Check({ task, onChange }: { task: Task; onChange: (done: boolean) => void }) {
  const done = task.status === "done";
  return <RoundCheck label={task.title} checked={done} onChange={onChange} />;
}

function TaskRow({ task }: { task: Task }) {
  const lead = useLeadName();
  // Suggestions come from the Mail agent, while it reads mail, so it is named, not the lead.
  const suggester = useAgentName()("mail") || lead;
  const save = useSaveTask();
  const remove = useRemoveTask();
  const formatDay = useDateOnly();
  const relative = useRelativeTime();
  const [title, setTitle] = useState(task.title);
  const [notes, setNotes] = useState(task.notes);
  useEffect(() => setTitle(task.title), [task.title]);
  useEffect(() => setNotes(task.notes), [task.notes]);
  const overdue = task.status !== "done" && task.due !== null && task.due !== undefined && task.due < today();
  const update = (changes: Partial<ReturnType<typeof fields>>) => save.mutate({ ...fields(task), ...changes });
  const done = task.status === "done";
  return (
    <Rise as="li" settle="position">
      <ContextMenu items={[{ id: "done", label: t(done ? "menu.markOpen" : "menu.markDone"), onSelect: () => update({ status: done ? "todo" : "done" }) }, { id: "remove", label: t("menu.remove"), icon: "trash", danger: true, onSelect: () => remove.mutate(task.id) }]}>
      {/* A suggestion wears the AI's edge until it's accepted, here and everywhere it shows. */}
      <div className={task.proposed ? "ai-edge rounded-lg" : ""} data-suggested={task.proposed || undefined}>
      <ExpandRow
        variant="list"
        testid="task"
        label={t("tasks.details", { title: task.title })}
        leading={task.proposed ? <SuggestedCheck round label={t("tasks.suggested.check")} /> : <Check task={task} onChange={(next) => update({ status: next ? "done" : "todo" })} />}
        title={<span className={done ? "text-ink-muted line-through" : ""}>{task.title}</span>}
        meta={
          <span className="flex min-w-0 items-center gap-2">
            {[
              task.proposed ? <span key="proposed" className="text-ink-secondary">{t("tasks.proposed", { name: suggester })}</span> : null,
              task.due ? <span key="due" className={overdue ? "font-medium text-status-danger" : ""}>{formatDay(task.due)}</span> : null,
              task.source_ref ? <SourceChip key="source" source={task.source_ref} look="inline" /> : null,
              task.source === "agent" && !task.proposed ? <span key="agent">{t("tasks.byAgent")}</span> : null,
              task.looks_done ? <span key="looks" className="font-medium text-status-success">{t("today.looksDone")}</span> : null,
              task.notes ? <span key="notes" className="min-w-0 truncate">{task.notes.split("\n")[0]}</span> : null,
            ].filter(Boolean).flatMap((item, index) => (index ? [<MetaDot key={`dot-${index}`} />, item] : [item]))}
          </span>
        }
        aside={
          task.proposed ? (
            <span className="flex shrink-0 items-center gap-1">
              <Button variant="quiet" onClick={() => remove.mutate(task.id)}>
                {t("tasks.dismiss")}
              </Button>
              <Button variant="primary" onClick={() => update({ proposed: false })}>
                {t("tasks.keep")}
              </Button>
            </span>
          ) : null
        }
      >
        <div className="grid gap-3 md:grid-cols-2">
          <div className="md:col-span-2">
            <Field label={t("tasks.title")}>{({ invalid, ...control }) => <Input invalid={invalid} value={title} onChange={(event) => setTitle(event.target.value)} onBlur={() => title.trim() && title !== task.title && update({ title: title.trim() })} {...control} />}</Field>
          </div>
          <Field label={t("tasks.statusLabel")}>{({ id }) => <Select compact id={id} value={task.status} options={STATUSES} onChange={(status) => update({ status: status as Task["status"] })} />}</Field>
          <Field label={t("tasks.due")}>{({ invalid, ...control }) => <Input className="py-1" type="date" invalid={invalid} value={task.due ?? ""} onChange={(event) => update({ due: event.target.value || null })} {...control} />}</Field>
          <div className="md:col-span-2">
            <Field label={t("tasks.notes")}>{({ invalid, ...control }) => <Textarea invalid={invalid} rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} onBlur={() => notes !== task.notes && update({ notes })} {...control} />}</Field>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p data-testid="task-times" className="text-sm tabular-nums text-ink-muted">
            {t(task.source === "agent" ? "tasks.addedByAgent" : "tasks.added", { when: relative(task.created) })}
            {task.updated && task.updated !== task.created ? ` · ${t("tasks.changed", { when: relative(task.updated) })}` : ""}
            {task.completed ? ` · ${t("tasks.finished", { when: relative(task.completed) })}` : ""}
          </p>
          <div className="flex items-center gap-1">
            <AskAgent context={[`task:${task.id}`]} title={task.title} label={t("tasks.doIt")} text={t("tasks.doIt.prompt")} quiet={false} />
            <IconButton icon="trash" label={t("tasks.remove", { title: task.title })} onClick={() => remove.mutate(task.id)} />
          </div>
        </div>
        {save.isError || remove.isError ? <ErrorState title={t("planner.saveFailed")} description={save.error?.message ?? remove.error?.message ?? ""} /> : null}
      </ExpandRow>
      </div>
      </ContextMenu>
    </Rise>
  );
}

export function TasksScreen() {
  const tasks = useTasks(true);
  const save = useSaveTask();
  const [view, setView] = useState<View>("open");
  const [title, setTitle] = useState("");
  const [due, setDue] = useState<string | null>(null);
  const all = tasks.data?.tasks ?? [];
  const suggested = all.filter((task) => task.proposed);
  const open = all.filter((task) => !task.proposed && task.status !== "done");
  const done = all.filter((task) => task.status === "done");
  const overdue = open.filter((task) => bucket(task) === "tasks.group.overdue").length;
  const shown = view === "open" ? open : suggested;
  const day = useShortDate();
  const add = () => save.mutate({ title: title.trim(), ...(due ? { due } : {}) }, { onSuccess: () => { setTitle(""); setDue(null); } });
  const groups = view === "open" ? ORDER.map((key) => ({ key, rows: shown.filter((task) => bucket(task) === key) })).filter((group) => group.rows.length) : [{ key: null, rows: shown }];
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-5 p-6">
      <PageHeader
        title={t("nav.tasks")}
        summary={tasks.data ? [tn("tasks.summary", open.length), overdue ? t("tasks.overdueCount", { count: overdue }) : null].filter(Boolean).join(" · ") : undefined}
        action={<Segmented hideLabel label={t("tasks.show")} value={view} onChange={setView} options={[
          { value: "open", label: t("tasks.view.open", { count: open.length }) },
          { value: "suggested", label: t("tasks.view.suggested", { count: suggested.length }) },
        ]} />}
      />
      <AddBar label={t("tasks.new")} placeholder={t("tasks.new.placeholder")} icon="add" value={title} onChange={setTitle} onSubmit={add} pending={save.isPending} ready={Boolean(title.trim())} picker={<DuePicker value={due} onChange={setDue} />} />
      {save.isError ? <ErrorState title={t("planner.saveFailed")} description={save.error.message} /> : null}
      {tasks.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {tasks.isError ? <ErrorState title={t("tasks.error")} onRetry={() => void tasks.refetch()} /> : null}
      {tasks.isSuccess && shown.length === 0 ? <EmptyState icon="tasks" title={t(view === "open" ? "tasks.empty" : "tasks.empty.suggested")} /> : null}
      <Presence>
        {groups.map((group) => (
          <Rise key={group.key ?? "all"} settle="position">
            <ListGroup title={group.key ? t(group.key) : t("tasks.view.suggestedTitle")} detail={String(group.rows.length)} {...(group.key === "tasks.group.overdue" ? { tone: "danger" as const } : {})}>
              <Presence>
                {group.rows.map((task) => (
                  <TaskRow key={task.id} task={task} />
                ))}
              </Presence>
            </ListGroup>
          </Rise>
        ))}
      </Presence>
      {view === "open" ? (
        <DoneGroup label={t("done.label")} count={done.length} testid="tasks-done">
          {done.map((task) => <DoneRow key={task.id} testid="task-done" title={task.title} meta={[task.completed ? day(task.completed) : null, task.looks_done || null].filter(Boolean).join(" · ")} action={<Button variant="quiet" onClick={() => save.mutate({ ...fields(task), status: "todo" })}>{t("menu.markOpen")}</Button>} />)}
        </DoneGroup>
      ) : null}
    </div>
  );
}
