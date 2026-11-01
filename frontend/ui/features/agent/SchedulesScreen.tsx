"use client";

import { useState } from "react";
import type { Schedule, ScheduleRow } from "@/ui/client/contracts.generated";
import { useDateTime } from "@/ui/client/format";
import { useRemoveSchedule, useRunSchedule, useSaveSchedule, useSchedules, useSetDefaults } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { Dialog } from "@/ui/primitives/Dialog";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Switch } from "@/ui/primitives/Switch";
import { TextLink } from "@/ui/primitives/TextLink";
import { t } from "@/ui/strings";

const EVERY = [
  { value: "day", label: t("schedules.every.day") },
  { value: "week", label: t("schedules.every.week") },
  { value: "once", label: t("schedules.every.once") },
];
const WEEKDAYS = ["schedules.day.0", "schedules.day.1", "schedules.day.2", "schedules.day.3", "schedules.day.4", "schedules.day.5", "schedules.day.6"] as const;

const HOURS_NOT_SET = "08:00";
const PREP_TIME = "06:00";

type Saved = Omit<Schedule, "id"> & { id?: number | null };

function ScheduleForm({ initial, action, onSaved }: { initial?: ScheduleRow; action: string; onSaved: () => void }) {
  const save = useSaveSchedule();
  const [title, setTitle] = useState(initial?.title ?? "");
  const [prompt, setPrompt] = useState(initial?.prompt ?? "");
  const [every, setEvery] = useState<NonNullable<Schedule["every"]>>(initial?.every ?? "day");
  const [time, setTime] = useState(initial?.time ?? HOURS_NOT_SET);
  const [weekday, setWeekday] = useState(String(initial?.weekday ?? 0));
  const [date, setDate] = useState(initial?.date ?? "");
  const [limit, setLimit] = useState(String(initial?.token_limit ?? 0));
  const isPrep = initial?.kind === "daily-prep";
  const values: Saved = {
    ...(initial ? { id: initial.id ?? null, kind: initial.kind ?? "prompt", enabled: initial.enabled ?? true } : {}),
    title: title.trim(),
    prompt,
    every,
    time,
    weekday: Number(weekday),
    date: date || null,
    token_limit: Number(limit) || 0,
  };
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(values as Schedule, {
          onSuccess: () => {
            if (!initial) {
              setTitle("");
              setPrompt("");
            }
            onSaved();
          },
        });
      }}
    >
      <Field label={t("schedules.name")}>{({ invalid, ...control }) => <Input invalid={invalid} value={title} onChange={(event) => setTitle(event.target.value)} {...control} />}</Field>
      <Field label={t(isPrep ? "schedules.scope" : "schedules.prompt")} {...(isPrep ? { hint: t("schedules.scope.hint") } : {})}>
        {({ invalid, ...control }) => <Textarea invalid={invalid} rows={2} value={prompt} onChange={(event) => setPrompt(event.target.value)} {...control} />}
      </Field>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label={t("schedules.every")}>{({ invalid, id }) => <Select id={id} invalid={invalid} value={every} options={EVERY} onChange={(value) => setEvery(value as typeof every)} />}</Field>
        <Field label={t("schedules.time")}>{({ invalid, ...control }) => <Input type="time" invalid={invalid} value={time} onChange={(event) => setTime(event.target.value)} {...control} />}</Field>
        {every === "week" ? <Field label={t("schedules.weekday")}>{({ invalid, id }) => <Select id={id} invalid={invalid} value={weekday} options={WEEKDAYS.map((key, index) => ({ value: String(index), label: t(key) }))} onChange={setWeekday} />}</Field> : null}
        {every === "once" ? <Field label={t("schedules.date")}>{({ invalid, ...control }) => <Input type="date" invalid={invalid} value={date} onChange={(event) => setDate(event.target.value)} {...control} />}</Field> : null}
      </div>
      <Field label={t("schedules.limit")} hint={t("schedules.limit.hint")}>{({ invalid, ...control }) => <Input type="number" min={0} invalid={invalid} value={limit} onChange={(event) => setLimit(event.target.value)} {...control} />}</Field>
      <div><Button type="submit" variant="primary" loading={save.isPending} disabled={!title.trim() || (!isPrep && !prompt.trim()) || (every === "once" && !date)}>{action}</Button></div>
    </form>
  );
}

function ScheduleItem({ row }: { row: ScheduleRow }) {
  const save = useSaveSchedule();
  const remove = useRemoveSchedule();
  const run = useRunSchedule();
  const format = useDateTime();
  const [editing, setEditing] = useState(false);
  return (
    <li data-testid="schedule" className="flex flex-col gap-2 rounded-md border border-line-subtle p-3">
      <div className="flex items-center justify-between gap-3">
        <span className="min-w-0 truncate text-md font-medium text-ink-primary">{row.title}</span>
        <IconButton icon="close" label={t("tasks.remove", { title: row.title })} onClick={() => row.id != null && remove.mutate(row.id)} />
      </div>
      <p className="text-sm tabular-nums text-ink-muted">
        {row.next_run ? t("schedules.next", { when: format(row.next_run) }) : t("schedules.noNext")}
        {row.token_limit ? ` · ${t("schedules.limit.value", { limit: row.token_limit.toLocaleString() })}` : ""}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button loading={run.isPending} onClick={() => row.id != null && run.mutate(row.id)}>{t("schedules.runNow")}</Button>
        <Dialog title={t("schedules.edit", { title: row.title })} open={editing} onOpenChange={setEditing} trigger={<Button>{t("schedules.editAction")}</Button>}>
          <ScheduleForm initial={row} action={t("settings.save")} onSaved={() => setEditing(false)} />
        </Dialog>
        <Switch label={t("rules.enabled")} checked={row.enabled ?? true} onChange={(enabled) => save.mutate({ id: row.id ?? null, title: row.title, prompt: row.prompt ?? "", kind: row.kind ?? "prompt", every: row.every ?? "day", time: row.time ?? HOURS_NOT_SET, weekday: row.weekday ?? 0, date: row.date ?? null, enabled, token_limit: row.token_limit ?? 0 })} />
        {row.last_session ? <TextLink className="text-sm" href={`/agent/sessions/${row.last_session}`}>{t("schedules.lastRun")}</TextLink> : null}
      </div>
    </li>
  );
}

export function SchedulesScreen() {
  const schedules = useSchedules();
  const save = useSaveSchedule();
  const defaults = useSetDefaults();
  const rows = schedules.data?.schedules ?? [];
  const hasPrep = rows.some((row) => row.kind === "daily-prep");
  return (
    <div className="mx-auto flex max-w-content flex-col gap-4 p-6">
      <h1 className="font-serif text-display text-ink-primary">{t("nav.schedules")}</h1>
      {schedules.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {schedules.isError ? <ErrorState title={t("schedules.error")} onRetry={() => void schedules.refetch()} /> : null}
      <Card title={t("schedules.defaults")} description={t("schedules.defaults.description")}>
        <div className="flex flex-col gap-3">
          <Switch label={t("schedules.liveMail")} checked={schedules.data?.live_mail_enabled ?? true} onChange={(live_mail_enabled) => defaults.mutate({ live_mail_enabled })} />
          <Switch label={t("schedules.timeCheck")} checked={schedules.data?.time_check_enabled ?? true} onChange={(time_check_enabled) => defaults.mutate({ time_check_enabled })} />
          {schedules.isSuccess && !hasPrep ? (
            <div><Button loading={save.isPending} onClick={() => save.mutate({ title: t("schedules.prep.title"), kind: "daily-prep", every: "day", time: PREP_TIME })}>{t("schedules.prep.add")}</Button></div>
          ) : null}
        </div>
      </Card>
      <ul aria-label={t("nav.schedules")} className="flex flex-col gap-2">
        {rows.map((row) => <ScheduleItem key={row.id} row={row} />)}
      </ul>
      <Card title={t("schedules.new")}>
        <ScheduleForm action={t("schedules.create")} onSaved={() => undefined} />
      </Card>
    </div>
  );
}
