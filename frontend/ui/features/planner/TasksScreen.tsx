"use client";

import { useEffect, useState } from "react";
import type { Task } from "@/ui/client/contracts.generated";
import { useDateOnly, useRelativeTime } from "@/ui/client/format";
import { useRemoveTask, useSaveTask, useTasks } from "@/ui/client/work";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { Icon } from "@/ui/icons";
import { RoundCheck } from "@/ui/primitives/Checkbox";
import { Button } from "@/ui/primitives/Button";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { PageHeader } from "@/ui/primitives/PageHeader";
import { BareInput } from "@/ui/primitives/Pressable";
import { Segmented } from "@/ui/primitives/Segmented";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { TextLink } from "@/ui/primitives/TextLink";
import { t, tn, type StringKey } from "@/ui/strings";

const STATUSES = [
  { value: "todo", label: t("tasks.status.todo") },
  { value: "in_progress", label: t("tasks.status.inProgress") },
  { value: "done", label: t("tasks.status.done") },
];

type View = "open" | "suggested" | "done";

const fields = (task: Task) => ({ id: task.id, title: task.title, notes: task.notes, status: task.status, due: task.due ?? null, thread: task.thread ?? null, proposed: task.proposed });

const today = () => new Date().toLocaleDateString("sv-SE");
const inDays = (days: number) => new Date(Date.now() + days * 86_400_000).toLocaleDateString("sv-SE");

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
      <div>
      <ExpandRow
        testid="task"
        label={t("tasks.details", { title: task.title })}
        leading={task.proposed ? <Icon name="thinking" className="h-4 w-4 shrink-0 text-accent-default" /> : <Check task={task} onChange={(next) => update({ status: next ? "done" : "todo" })} />}
        title={<span className={done ? "text-ink-muted line-through" : ""}>{task.title}</span>}
        meta={
          <span className="flex items-center gap-2">
            {task.proposed ? <span className="text-accent-default">{t("tasks.proposed")}</span> : null}
            {task.due ? <span className={overdue ? "text-accent-default" : ""}>{formatDay(task.due)}</span> : null}
            {task.notes ? <span className="truncate">{task.notes.split("\n")[0]}</span> : null}
          </span>
        }
        aside={
          task.proposed ? (
            <span className="flex shrink-0 items-center gap-1">
              <Button variant="quiet" onClick={() => remove.mutate(task.id)}>
                {t("memory.decline")}
              </Button>
              <Button variant="primary" onClick={() => update({ proposed: false })}>
                {t("tasks.accept")}
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
            {task.thread ? <TextLink className="mr-2 text-sm" href={`/mail/all/${task.thread}`}>{t("channel.openSource")}</TextLink> : null}
            <AskAgent context={[`task:${task.id}`]} title={task.title} label={t("tasks.doIt")} text={t("tasks.doIt.prompt")} quiet={false} />
            <IconButton icon="trash" label={t("tasks.remove", { title: task.title })} onClick={() => remove.mutate(task.id)} />
          </div>
        </div>
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
  const [due, setDue] = useState("");
  const all = tasks.data?.tasks ?? [];
  const suggested = all.filter((task) => task.proposed);
  const open = all.filter((task) => !task.proposed && task.status !== "done");
  const done = all.filter((task) => task.status === "done");
  const shown = view === "open" ? open : view === "suggested" ? suggested : done;
  const add = () => {
    if (!title.trim()) return;
    save.mutate({ title: title.trim(), ...(due ? { due } : {}) }, { onSuccess: () => { setTitle(""); setDue(""); } });
  };
  const groups = view === "open" ? ORDER.map((key) => ({ key, rows: shown.filter((task) => bucket(task) === key) })).filter((group) => group.rows.length) : [{ key: null, rows: shown }];
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-5 p-6">
      <PageHeader title={t("nav.tasks")} summary={tasks.data ? tn("tasks.summary", open.length) : undefined} />
      <form
        className="flex items-center gap-2 rounded-lg border border-line-subtle bg-surface-raised p-2 transition-colors duration-fast focus-within:border-line-strong"
        onSubmit={(event) => {
          event.preventDefault();
          add();
        }}
      >
        <BareInput aria-label={t("tasks.new")} placeholder={t("tasks.new.placeholder")} value={title} onChange={(event) => setTitle(event.target.value)} className="min-w-0 flex-1 bg-transparent px-2 py-1 text-md text-ink-primary outline-none placeholder:text-ink-muted" />
        <BareInput aria-label={t("tasks.due")} type="date" value={due} onChange={(event) => setDue(event.target.value)} className="focus-ring rounded-md bg-transparent px-2 py-1 text-sm text-ink-secondary" />
        <Button type="submit" variant="primary" loading={save.isPending} disabled={!title.trim()}>
          {t("tasks.add")}
        </Button>
      </form>
      <Segmented
        hideLabel
        label={t("tasks.show")}
        value={view}
        onChange={setView}
        options={[
          { value: "open", label: t("tasks.view.open", { count: open.length }) },
          { value: "suggested", label: t("tasks.view.suggested", { count: suggested.length }) },
          { value: "done", label: t("tasks.view.done", { count: done.length }) },
        ]}
      />
      {tasks.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {tasks.isError ? <ErrorState title={t("tasks.error")} onRetry={() => void tasks.refetch()} /> : null}
      {tasks.isSuccess && shown.length === 0 ? <EmptyState icon="tasks" title={t(view === "open" ? "tasks.empty" : view === "suggested" ? "tasks.empty.suggested" : "tasks.empty.done")} /> : null}
      <div className="flex flex-col gap-5">
        {groups.map((group) => (
          <section key={group.key ?? "all"} {...(group.key ? { "aria-label": t(group.key) } : {})} className="flex flex-col gap-2">
            {group.key ? <h2 className={`text-sm ${group.key === "tasks.group.overdue" ? "text-accent-default" : "text-ink-muted"}`}>{t(group.key)}</h2> : null}
            <ul aria-label={group.key ? t(group.key) : t("nav.tasks")} className="flex flex-col gap-2">
              <Presence>
                {group.rows.map((task) => (
                  <TaskRow key={task.id} task={task} />
                ))}
              </Presence>
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
