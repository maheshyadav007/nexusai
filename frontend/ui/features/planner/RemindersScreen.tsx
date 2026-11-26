"use client";

import { useLeadName } from "@/ui/client/home";
import { useEffect, useState } from "react";
import type { Reminder } from "@/ui/client/contracts.generated";
import { useRelativeTime, useShortDate, useTimeOnly } from "@/ui/client/format";
import { AddBar, dayAt, localMoment, QUICK_TIMES, REPEATS, WhenPicker } from "./AddBar";
import { useReminders, useRemoveReminder, useSaveReminder, useSnooze } from "@/ui/client/work";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { DoneGroup, DoneRow } from "@/ui/primitives/DoneGroup";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Menu } from "@/ui/primitives/Menu";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { ListGroup, MetaDot } from "@/ui/primitives/List";
import { PageHeader } from "@/ui/primitives/PageHeader";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t, tn, type StringKey } from "@/ui/strings";
import { SourceChip } from "@/ui/features/sources/SourceChip";
import { repeatText } from "./repeatText";

type Repeat = Reminder["repeat"];
const MINUTE = 60_000;
const WEEK_DAYS = 7;

function bucket(when: string): StringKey {
  const date = new Date(when);
  if (date.getTime() < Date.now()) return "reminders.group.past";
  const day = date.toDateString();
  if (day === new Date().toDateString()) return "reminders.group.today";
  if (day === dayAt(1).toDateString()) return "reminders.group.tomorrow";
  if (date.getTime() < dayAt(WEEK_DAYS).getTime()) return "reminders.group.week";
  return "reminders.group.later";
}
const ORDER: readonly StringKey[] = ["reminders.group.past", "reminders.group.today", "reminders.group.tomorrow", "reminders.group.week", "reminders.group.later"];

function ReminderRow({ reminder }: { reminder: Reminder }) {
  const save = useSaveReminder();
  const snooze = useSnooze();
  const remove = useRemoveReminder();
  const lead = useLeadName();
  const clock = useTimeOnly();
  const day = useShortDate();
  const relative = useRelativeTime();
  const [title, setTitle] = useState(reminder.title);
  useEffect(() => setTitle(reminder.title), [reminder.title]);
  // The whole rule goes back with every change, so renaming an hourly reminder keeps its hours.
  const rule = { every_minutes: reminder.every_minutes ?? null, days: reminder.days ?? null, window_start: reminder.window_start ?? null, window_end: reminder.window_end ?? null, until: reminder.until ?? null };
  const update = (changes: { title?: string; when?: string; repeat?: Repeat; proposed?: boolean }) => save.mutate({ id: reminder.id, title: reminder.title, when: reminder.when, repeat: reminder.repeat, thread: reminder.thread ?? null, task: reminder.task ?? null, proposed: reminder.proposed, ...rule, ...changes });
  const repeats = repeatText(reminder, day);
  const options = reminder.repeat === "interval" ? [{ value: "interval", label: repeats }, ...REPEATS] : REPEATS;
  const later = (target: Date) => snooze.mutate({ id: reminder.id, minutes: Math.max(1, Math.round((target.getTime() - Date.now()) / MINUTE)) });
  const sameDay = new Date(reminder.when).toDateString() === new Date().toDateString();
  return (
    <Rise as="li" settle="position" className={reminder.proposed ? "ai-edge rounded-lg" : ""}>
      <ExpandRow
        variant="list"
        testid="reminder"
        label={t("reminders.details", { title: reminder.title })}
        leading={
          <span className="flex w-guide shrink-0 flex-col tabular-nums">
            <span className={`text-md font-medium ${sameDay ? "text-accent-default" : "text-ink-primary"}`}>{clock(reminder.when)}</span>
            {sameDay ? null : <span className="text-sm text-ink-muted">{day(reminder.when)}</span>}
          </span>
        }
        title={reminder.title}
        meta={(() => {
          const bits = [
            reminder.proposed ? <span key="proposed" className="text-ink-secondary">{t("tasks.proposed", { name: lead })}</span> : null,
            reminder.repeat !== "none" ? <span key="repeat" className="flex items-center gap-1"><Icon name="repeat" className="h-3 w-3" />{repeats}</span> : null,
            reminder.source_ref ? <SourceChip key="source" source={reminder.source_ref} look="inline" /> : null,
            reminder.source === "agent" && !reminder.proposed ? <span key="agent">{t("reminders.byAgent")}</span> : null,
          ].filter(Boolean);
          return bits.length ? <span className="flex min-w-0 items-center gap-2">{bits.flatMap((item, index) => (index ? [<MetaDot key={`dot-${index}`} />, item] : [item]))}</span> : undefined;
        })()}
        aside={
          reminder.proposed ? (
            <span className="flex shrink-0 items-center gap-1">
              <Button variant="quiet" onClick={() => remove.mutate(reminder.id)}>
                {t("memory.decline")}
              </Button>
              <Button variant="primary" onClick={() => update({ proposed: false })}>
                {t("tasks.accept")}
              </Button>
            </span>
          ) : (
            <Menu trigger={<Button variant="quiet">{t("reminders.snooze")}</Button>} items={QUICK_TIMES.map(({ key, when }) => ({ id: key, label: t(key), onSelect: () => later(when()) }))} />
          )
        }
      >
        <Field label={t("reminders.what")}>{({ invalid, ...control }) => <Input invalid={invalid} value={title} onChange={(event) => setTitle(event.target.value)} onBlur={() => title.trim() && title !== reminder.title && update({ title: title.trim() })} {...control} />}</Field>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label={t("reminders.when")}>{({ invalid, ...control }) => <Input className="py-1" type="datetime-local" invalid={invalid} value={localMoment(new Date(reminder.when))} onChange={(event) => event.target.value && update({ when: event.target.value })} {...control} />}</Field>
          <Field label={t("reminders.repeat")}>{({ id }) => <Select compact id={id} value={reminder.repeat} options={options} onChange={(repeat) => update({ repeat: repeat as Repeat })} />}</Field>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p data-testid="reminder-times" className="text-sm tabular-nums text-ink-muted">
            {reminder.created ? t(reminder.source === "agent" ? "tasks.addedByAgent" : "tasks.added", { when: relative(reminder.created) }) : ""}
            {reminder.updated && reminder.updated !== reminder.created ? ` · ${t("tasks.changed", { when: relative(reminder.updated) })}` : ""}
          </p>
          <div className="flex items-center gap-1">
            <IconButton icon="trash" label={t("tasks.remove", { title: reminder.title })} onClick={() => remove.mutate(reminder.id)} />
          </div>
        </div>
        {save.isError || snooze.isError || remove.isError ? <ErrorState title={t("planner.saveFailed")} description={save.error?.message ?? snooze.error?.message ?? remove.error?.message ?? ""} /> : null}
      </ExpandRow>
    </Rise>
  );
}

export function RemindersScreen() {
  const reminders = useReminders(true);
  const save = useSaveReminder();
  const remove = useRemoveReminder();
  const clock = useTimeOnly();
  const day = useShortDate();
  const [title, setTitle] = useState("");
  const [when, setWhen] = useState(() => localMoment(QUICK_TIMES[2]!.when()));
  const [repeat, setRepeat] = useState<Repeat>("none");
  const all = reminders.data?.reminders ?? [];
  const rows = all.filter((row) => !row.fired).sort((a, b) => a.when.localeCompare(b.when));
  const done = all.filter((row) => row.fired).sort((a, b) => b.when.localeCompare(a.when));
  const groups = ORDER.map((key) => ({ key, rows: rows.filter((row) => bucket(row.when) === key) })).filter((group) => group.rows.length);
  const next = rows.find((row) => new Date(row.when).getTime() >= Date.now());
  const add = () => save.mutate({ title: title.trim(), when, repeat }, { onSuccess: () => { setTitle(""); setRepeat("none"); } });
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-5 p-6">
      <PageHeader title={t("nav.reminders")} summary={reminders.data ? [tn("reminders.summary", rows.length), next ? t("reminders.next", { when: clock(next.when) }) : null].filter(Boolean).join(" · ") : undefined} />
      <AddBar label={t("reminders.what")} placeholder={t("reminders.what.placeholder")} icon="reminders" value={title} onChange={setTitle} onSubmit={add} pending={save.isPending} ready={Boolean(title.trim() && when)} picker={<WhenPicker value={when} repeat={repeat} onChange={setWhen} onRepeat={setRepeat} />} />
      {save.isError ? <ErrorState title={t("planner.saveFailed")} description={save.error.message} /> : null}
      {reminders.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {reminders.isError ? <ErrorState title={t("reminders.error")} onRetry={() => void reminders.refetch()} /> : null}
      {reminders.isSuccess && rows.length === 0 ? <EmptyState icon="reminders" title={t("reminders.empty")} /> : null}
      <Presence>
        {groups.map((group) => (
          <Rise key={group.key} settle="position">
            <ListGroup title={t(group.key)} detail={String(group.rows.length)} {...(group.key === "reminders.group.past" ? { tone: "danger" as const } : {})}>
              <Presence>
                {group.rows.map((reminder) => (
                  <ReminderRow key={reminder.id} reminder={reminder} />
                ))}
              </Presence>
            </ListGroup>
          </Rise>
        ))}
      </Presence>
      <DoneGroup label={t("done.label")} count={done.length} testid="reminders-done">
        {done.map((reminder) => <DoneRow key={reminder.id} testid="reminder-done" title={reminder.title} meta={t("reminders.wentOff", { when: day(reminder.when) })} action={<IconButton icon="trash" label={t("tasks.remove", { title: reminder.title })} onClick={() => remove.mutate(reminder.id)} />} />)}
      </DoneGroup>
    </div>
  );
}
