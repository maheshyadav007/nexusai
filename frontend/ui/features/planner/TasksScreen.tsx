"use client";

import { useState } from "react";
import type { Task } from "@/ui/client/contracts.generated";
import { useRemoveTask, useSaveTask, useTasks } from "@/ui/client/work";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { TextLink } from "@/ui/primitives/TextLink";
import { t } from "@/ui/strings";

const editable = (task: Task) => ({ id: task.id, title: task.title, notes: task.notes, status: task.status, due: task.due ?? null, thread: task.thread ?? null, proposed: task.proposed });

export function TasksScreen() {
  const [showDone, setShowDone] = useState(false);
  const tasks = useTasks(showDone);
  const save = useSaveTask();
  const remove = useRemoveTask();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const rows = tasks.data?.tasks ?? [];
  return (
    <div className="mx-auto flex max-w-content flex-col gap-4 p-6">
      <h1 className="font-serif text-display text-ink-primary">{t("nav.tasks")}</h1>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate({ title: title.trim(), ...(due ? { due } : {}) }, { onSuccess: () => { setTitle(""); setDue(""); } });
        }}
      >
        <div className="min-w-0 flex-1"><Field label={t("tasks.new")}>{({ invalid, ...control }) => <Input invalid={invalid} value={title} onChange={(event) => setTitle(event.target.value)} {...control} />}</Field></div>
        <Field label={t("tasks.due")}>{({ invalid, ...control }) => <Input type="date" invalid={invalid} value={due} onChange={(event) => setDue(event.target.value)} {...control} />}</Field>
        <Button type="submit" variant="primary" loading={save.isPending} disabled={!title.trim()}>{t("tasks.add")}</Button>
      </form>
      <Checkbox label={t("tasks.showDone")} checked={showDone} onChange={setShowDone} />
      {tasks.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {tasks.isError ? <ErrorState title={t("tasks.error")} onRetry={() => void tasks.refetch()} /> : null}
      {tasks.isSuccess && rows.length === 0 ? <EmptyState icon="tasks" title={t("tasks.empty")} /> : null}
      <ul aria-label={t("nav.tasks")} className="flex flex-col gap-2">
        {rows.map((task) => (
          <li key={task.id} data-testid="task" className="flex flex-col gap-2 rounded-md border border-line-subtle p-3">
            <div className="flex items-center justify-between gap-3">
              <Checkbox label={task.title} checked={task.status === "done"} onChange={(done) => save.mutate({ ...editable(task), status: done ? "done" : "todo" })} />
              <span className="flex shrink-0 items-center gap-2">
                {task.due ? <span className="text-sm tabular-nums text-ink-muted">{task.due}</span> : null}
                {task.proposed ? <Badge tone="accent">{t("tasks.proposed")}</Badge> : null}
                <IconButton icon="close" label={t("tasks.remove", { title: task.title })} onClick={() => remove.mutate(task.id)} />
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {task.proposed ? <Button variant="primary" onClick={() => save.mutate({ ...editable(task), proposed: false })}>{t("tasks.accept")}</Button> : null}
              <AskAgent context={[`task:${task.id}`]} title={task.title} label={t("tasks.doIt")} />
              {task.thread ? <TextLink className="text-sm" href={`/mail/thread/${task.thread}`}>{t("channel.openSource")}</TextLink> : null}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
