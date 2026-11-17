"use client";

import { useState } from "react";
import type { Schedule, ScheduleRow, Trigger } from "@/ui/client/contracts.generated";
import { useDateOnly, useDateTime, useRelativeTime, useTimeOnly } from "@/ui/client/format";
import { useAgentName, usePausePipeline, usePipelines, useRemoveSchedule, useRunSchedule, useSaveSchedule, useSaveTrigger, useSchedules, useSetDefaults, useTriggers } from "@/ui/client/work";
import { SessionGeneration } from "@/ui/features/agent/SessionGeneration";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { SessionLink } from "@/ui/features/assistant/SessionLink";
import { PIPELINE_TONES } from "@/ui/features/cockpit/Pipelines";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input, Textarea } from "@/ui/primitives/Input";
import { ListGroup, ListRow } from "@/ui/primitives/List";
import { PageHeader } from "@/ui/primitives/PageHeader";
import { Segmented } from "@/ui/primitives/Segmented";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { Switch } from "@/ui/primitives/Switch";
import { MoreOptions, runOptions, savedRunOptions } from "./RunOptions";
import { TriggerForm, triggerSaved } from "./TriggerForm";
import { t, type StringKey } from "@/ui/strings";

type Every = NonNullable<Schedule["every"]>;
const REPEATS: readonly Every[] = ["once", "hour", "day", "week"];
const WEEKDAYS = ["schedules.day.0", "schedules.day.1", "schedules.day.2", "schedules.day.3", "schedules.day.4", "schedules.day.5", "schedules.day.6"] as const;
const DEFAULT_TIME = "08:00";
const PREP_TIME = "06:00";
const FRIDAY = 4;
const MONDAY = 0;

/** Ready-made schedules: a name, what to do and when, for the person to adjust before saving. */
const TEMPLATES: readonly { title: StringKey; prompt?: StringKey; kind?: Schedule["kind"]; every: Every; time: string; weekday?: number }[] = [
  { title: "schedules.template.prep", kind: "daily-prep", every: "day", time: PREP_TIME },
  { title: "schedules.template.weekly", prompt: "schedules.template.weekly.prompt", every: "week", time: "17:00", weekday: FRIDAY },
  { title: "schedules.template.monday", prompt: "schedules.template.monday.prompt", every: "week", time: "09:00", weekday: MONDAY },
  { title: "schedules.template.deadlines", prompt: "schedules.template.deadlines.prompt", every: "day", time: DEFAULT_TIME },
];
type Template = (typeof TEMPLATES)[number];

type Open = { schedule: number } | { trigger: string } | { create: Template | null };

const saved = (row: ScheduleRow, enabled = row.enabled ?? true): Schedule => ({
  id: row.id ?? null,
  title: row.title,
  prompt: row.prompt ?? "",
  kind: row.kind ?? "prompt",
  every: row.every ?? "day",
  time: row.time ?? DEFAULT_TIME,
  timezone: row.timezone ?? null,
  weekday: row.weekday ?? 0,
  date: row.date ?? null,
  enabled,
  token_limit: row.token_limit ?? 0,
  context_mode: row.context_mode ?? null,
  keep_messages: row.keep_messages ?? null,
});

/** "Every Friday at 5:00 PM", in the person's own time format. */
function useCadence() {
  const clock = useTimeOnly();
  const day = useDateOnly();
  return (row: Pick<Schedule, "every" | "time" | "weekday" | "date">) => {
    const time = row.time ?? DEFAULT_TIME;
    const at = clock(`2000-01-01T${time}`);
    if (row.every === "once") return row.date ? t("schedules.cadence.once", { date: day(row.date), time: at }) : t("schedules.cadence.onceNoDate", { time: at });
    if (row.every === "hour") return t("schedules.cadence.hour", { minute: time.slice(3) });
    if (row.every === "week") return t("schedules.cadence.week", { day: t(WEEKDAYS[row.weekday ?? 0] ?? "schedules.day.0"), time: at });
    return t("schedules.cadence.day", { time: at });
  };
}

function ScheduleForm({ initial, template, onSaved }: { initial?: ScheduleRow; template?: Template | null; onSaved: () => void }) {
  const save = useSaveSchedule();
  const remove = useRemoveSchedule();
  const [title, setTitle] = useState(initial?.title ?? (template ? t(template.title) : ""));
  const [prompt, setPrompt] = useState(initial?.prompt ?? (template?.prompt ? t(template.prompt) : ""));
  const [every, setEvery] = useState<Every>(initial?.every ?? template?.every ?? "day");
  const [time, setTime] = useState(initial?.time ?? template?.time ?? DEFAULT_TIME);
  const [weekday, setWeekday] = useState(String(initial?.weekday ?? template?.weekday ?? 0));
  const [date, setDate] = useState(initial?.date ?? "");
  const [timezone, setTimezone] = useState(initial?.timezone ?? "");
  const [options, setOptions] = useState(runOptions(initial));
  const kind = initial?.kind ?? template?.kind ?? "prompt";
  const isPrep = kind === "daily-prep";
  const values: Schedule = {
    ...(initial ? { id: initial.id ?? null, enabled: initial.enabled ?? true } : {}),
    kind,
    title: title.trim(),
    prompt,
    every,
    time,
    timezone: timezone.trim() || null,
    weekday: Number(weekday),
    date: date || null,
    ...savedRunOptions(options),
  };
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(values, { onSuccess: onSaved });
      }}
    >
      <Field label={t("schedules.name")}>{({ invalid, ...control }) => <Input invalid={invalid} value={title} onChange={(event) => setTitle(event.target.value)} {...control} />}</Field>
      <Field label={t(isPrep ? "schedules.scope" : "schedules.prompt")} {...(isPrep ? { hint: t("schedules.scope.hint") } : {})}>
        {({ invalid, ...control }) => <Textarea invalid={invalid} rows={3} value={prompt} onChange={(event) => setPrompt(event.target.value)} {...control} />}
      </Field>
      <div className="flex flex-col gap-3">
        <Segmented label={t("schedules.every")} value={every} options={REPEATS.map((value) => ({ value, label: t(`schedules.repeat.${value}`) }))} onChange={setEvery} />
        <div className="grid grid-cols-2 gap-3">
          {every === "week" ? <Field label={t("schedules.weekday")}>{({ invalid, id }) => <Select id={id} invalid={invalid} value={weekday} options={WEEKDAYS.map((key, index) => ({ value: String(index), label: t(key) }))} onChange={setWeekday} />}</Field> : null}
          {every === "once" ? <Field label={t("schedules.date")}>{({ invalid, ...control }) => <Input type="date" invalid={invalid} value={date} onChange={(event) => setDate(event.target.value)} {...control} />}</Field> : null}
          <Field label={t("schedules.time")}>{({ invalid, ...control }) => <Input type="time" invalid={invalid} value={time} onChange={(event) => setTime(event.target.value)} {...control} />}</Field>
        </div>
      </div>
      <MoreOptions values={options} onChange={setOptions}>
        <Field label={t("schedules.timezone")} hint={t("schedules.timezone.hint")}>{({ invalid, ...control }) => <Input {...control} invalid={invalid} value={timezone} onChange={(event) => setTimezone(event.target.value)} />}</Field>
      </MoreOptions>
      <div className="flex items-center justify-between gap-3">
        <Button type="submit" variant="primary" loading={save.isPending} disabled={!title.trim() || (!isPrep && !prompt.trim()) || (every === "once" && !date)}>{t(initial ? "settings.save" : "schedules.create")}</Button>
        {initial?.id != null ? <Button variant="quiet" loading={remove.isPending} onClick={() => remove.mutate(initial.id as number, { onSuccess: onSaved })}>{t("schedules.remove")}</Button> : null}
      </div>
    </form>
  );
}

/** What it is, when it runs next, and what it did last, above the form that changes it. */
function ScheduleDetails({ row, onDone }: { row: ScheduleRow; onDone: () => void }) {
  const run = useRunSchedule();
  const cadence = useCadence();
  const format = useDateTime(row.timezone);
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3">
        <p className="text-md tabular-nums text-ink-secondary">
          {cadence(row)}
          {row.enabled !== false && row.next_run ? ` · ${t("schedules.nextIn", { when: format(row.next_run) })}` : ""}
          {row.enabled === false ? ` · ${t("schedules.paused")}` : ""}
        </p>
        {row.last_run ? <p className="text-sm tabular-nums text-ink-muted">{t("schedules.ranLast", { when: format(row.last_run) })}</p> : null}
        <div className="flex flex-wrap items-center gap-3">
          <Button loading={run.isPending} onClick={() => row.id != null && run.mutate(row.id)}>{t("schedules.runNow")}</Button>
          {row.last_session ? <SessionLink className="text-md" session={row.last_session}>{t("schedules.lastRun")}</SessionLink> : null}
        </div>
        <SessionGeneration session={row.last_session} />
      </div>
      <ScheduleForm key={row.updated ?? row.id} initial={row} onSaved={onDone} />
    </div>
  );
}

function NewSchedule({ template, onTemplate, onDone }: { template: Template | null; onTemplate: (template: Template | null) => void; onDone: () => void }) {
  const [kind, setKind] = useState<"clock" | "event">("clock");
  return (
    <div className="flex flex-col gap-5">
      <Segmented label={t("schedules.kind")} value={kind} options={[{ value: "clock", label: t("schedules.kind.clock") }, { value: "event", label: t("schedules.kind.event") }]} onChange={setKind} />
      {kind === "clock" ? (
        <>
          <div className="flex flex-col gap-2">
            <span className="text-md text-ink-secondary">{t("schedules.templates")}</span>
            <div className="flex flex-wrap gap-2">
              {TEMPLATES.map((item) => (
                <Button key={item.title} variant={template === item ? "primary" : "secondary"} aria-pressed={template === item} onClick={() => onTemplate(template === item ? null : item)}>{t(item.title)}</Button>
              ))}
            </div>
          </div>
          <ScheduleForm key={template?.title ?? "blank"} template={template} onSaved={onDone} />
        </>
      ) : (
        <TriggerForm onSaved={onDone} />
      )}
    </div>
  );
}

function ScheduleItem({ row, onOpen }: { row: ScheduleRow; onOpen: () => void }) {
  const save = useSaveSchedule();
  const cadence = useCadence();
  const relative = useRelativeTime();
  const on = row.enabled ?? true;
  return (
    <ListRow
      testid="schedule"
      state={on ? "on" : "paused"}
      lead={<StatusDot tone={on ? "done" : "idle"} />}
      title={row.title}
      meta={`${cadence(row)} · ${on && row.next_run ? t("schedules.nextIn", { when: relative(row.next_run) }) : t(on ? "schedules.noNext" : "schedules.paused")}`}
      onOpen={onOpen}
      trailing={<Switch label={t("rules.enabled")} hideLabel checked={on} onChange={(enabled) => save.mutate(saved(row, enabled))} />}
    />
  );
}

function TriggerItem({ trigger, label, onOpen }: { trigger: Trigger; label: string; onOpen: () => void }) {
  const save = useSaveTrigger();
  const on = trigger.enabled ?? true;
  return (
    <ListRow
      testid="trigger"
      state={on ? "on" : "paused"}
      lead={<StatusDot tone={on ? "done" : "idle"} />}
      title={trigger.title}
      meta={on ? label : `${label} · ${t("schedules.paused")}`}
      onOpen={onOpen}
      trailing={<Switch label={t("rules.enabled")} hideLabel checked={on} onChange={(enabled) => save.mutate(triggerSaved(trigger, enabled))} />}
    />
  );
}

/** What comes with the app: mail sync on its timer, and the two checks that run by default. */
function BuiltIn({ liveMail, timeCheck }: { liveMail: boolean; timeCheck: boolean }) {
  const pipelines = usePipelines();
  const pause = usePausePipeline();
  const defaults = useSetDefaults();
  const relative = useRelativeTime();
  return (
    <ListGroup title={t("schedules.group.builtIn")}>
      {pipelines.data?.pipelines.map((row) => {
        const stopped = row.state === "stopped";
        return (
          <ListRow
            key={row.id}
            testid="pipeline"
            lead={<StatusDot tone={PIPELINE_TONES[row.state]} />}
            title={row.title}
            meta={[row.cadence, row.message || (row.last_run ? t("pipelines.lastRun", { when: relative(row.last_run) }) : null)].filter(Boolean).join(" · ")}
            trailing={row.available ? <Button variant="quiet" loading={pause.isPending} onClick={() => pause.mutate({ id: row.id, paused: !stopped })}>{t(stopped ? "pipelines.resume" : "pipelines.pause")}</Button> : null}
          />
        );
      })}
      <ListRow lead={<StatusDot tone={liveMail ? "done" : "idle"} />} title={t("schedules.liveMail")} trailing={<Switch label={t("schedules.liveMail")} hideLabel checked={liveMail} onChange={(live_mail_enabled) => defaults.mutate({ live_mail_enabled })} />} />
      <ListRow lead={<StatusDot tone={timeCheck ? "done" : "idle"} />} title={t("schedules.timeCheck")} trailing={<Switch label={t("schedules.timeCheck")} hideLabel checked={timeCheck} onChange={(time_check_enabled) => defaults.mutate({ time_check_enabled })} />} />
    </ListGroup>
  );
}

export function SchedulesScreen() {
  const schedules = useSchedules();
  const triggers = useTriggers();
  const relative = useRelativeTime();
  const mailAgent = useAgentName()("mail");
  const [open, setOpen] = useState<Open | null>(null);
  const rows = schedules.data?.schedules ?? [];
  const triggerRows = triggers.data?.triggers ?? [];
  const yours = triggerRows.filter((trigger) => trigger.kind !== "mail");
  const next = rows.filter((row) => row.enabled !== false && row.next_run).sort((a, b) => (a.next_run as string).localeCompare(b.next_run as string))[0];
  const labelOf = (trigger: Trigger) => (trigger.kind === "mail" ? t("triggers.builtIn", { agent: mailAgent }) : (triggers.data?.events.find((row) => row.event === trigger.event)?.label ?? trigger.event));
  const editing = open && "schedule" in open ? rows.find((row) => row.id === open.schedule) : undefined;
  const editingTrigger = open && "trigger" in open ? triggerRows.find((row) => row.id === open.trigger) : undefined;
  const close = () => setOpen(null);
  const title = editing?.title ?? editingTrigger?.title ?? t("schedules.new");
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-6 p-6">
      <PageHeader
        title={t("nav.schedules")}
        summary={next?.next_run ? t("schedules.summary.next", { title: next.title, when: relative(next.next_run) }) : t("schedules.summary")}
        action={<Button variant="primary" onClick={() => setOpen({ create: null })}>{t("schedules.add")}</Button>}
      />
      {schedules.isPending || triggers.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {schedules.isError ? <ErrorState title={t("schedules.error")} onRetry={() => void schedules.refetch()} /> : null}
      {triggers.isError ? <ErrorState title={t("triggers.error")} onRetry={() => void triggers.refetch()} /> : null}
      {schedules.isSuccess && triggers.isSuccess && !rows.length && !yours.length ? (
        <div className="flex flex-col gap-4 rounded-lg border border-line-subtle bg-surface-raised p-5">
          <EmptyState icon="schedules" title={t("schedules.empty.title")} description={t("schedules.empty.description")} />
          <div className="flex flex-wrap gap-2">
            {TEMPLATES.map((item) => <Button key={item.title} onClick={() => setOpen({ create: item })}>{t(item.title)}</Button>)}
            <AskAgent context={[]} title={t("schedules.ask.title")} label={t("schedules.ask")} />
          </div>
        </div>
      ) : null}
      {rows.length ? (
        <ListGroup title={t("schedules.group.clock")}>
          {rows.map((row) => <ScheduleItem key={row.id} row={row} onOpen={() => row.id != null && setOpen({ schedule: row.id })} />)}
        </ListGroup>
      ) : null}
      {triggerRows.length ? (
        <ListGroup title={t("triggers.title")}>
          {triggerRows.map((trigger) => <TriggerItem key={trigger.id} trigger={trigger} label={labelOf(trigger)} onOpen={() => setOpen({ trigger: trigger.id })} />)}
        </ListGroup>
      ) : null}
      {schedules.data ? <BuiltIn liveMail={schedules.data.live_mail_enabled} timeCheck={schedules.data.time_check_enabled} /> : null}
      <Dialog title={title} shape="drawer" open={open !== null} onOpenChange={(next) => (next ? null : close())}>
        <div className="-mx-5 min-h-0 flex-1 overflow-y-auto px-5 pb-5">
          {editing ? <ScheduleDetails row={editing} onDone={close} /> : null}
          {editingTrigger ? <TriggerForm key={editingTrigger.id} initial={editingTrigger} onSaved={close} /> : null}
          {open && "create" in open ? <NewSchedule template={open.create} onTemplate={(template) => setOpen({ create: template })} onDone={close} /> : null}
        </div>
      </Dialog>
    </div>
  );
}
