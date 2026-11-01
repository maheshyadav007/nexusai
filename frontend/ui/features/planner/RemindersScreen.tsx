"use client";

import { useEffect, useState } from "react";
import type { Reminder } from "@/ui/client/contracts.generated";
import { useRelativeTime, useShortDate, useTimeOnly } from "@/ui/client/format";
import { useReminders, useRemoveReminder, useSaveReminder, useSnooze } from "@/ui/client/work";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Menu } from "@/ui/primitives/Menu";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { PageHeader } from "@/ui/primitives/PageHeader";
import { BareInput, Pressable } from "@/ui/primitives/Pressable";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { TextLink } from "@/ui/primitives/TextLink";
import { t, tn, type StringKey } from "@/ui/strings";

const REPEATS = [
  { value: "none", label: t("reminders.repeat.none") },
  { value: "day", label: t("reminders.repeat.day") },
  { value: "week", label: t("reminders.repeat.week") },
];
type Repeat = Reminder["repeat"];

const MINUTE = 60_000;
const EVENING_HOUR = 18;
const MORNING_HOUR = 9;
const WEEK_DAYS = 7;

/** A moment in the form a time field and the backend use, in local time. */
const local = (date: Date) => new Date(date.getTime() - date.getTimezoneOffset() * MINUTE).toISOString().slice(0, 16);

function at(daysAhead: number, hour: number): Date {
  const date = new Date();
  date.setDate(date.getDate() + daysAhead);
  date.setHours(hour, 0, 0, 0);
  return date;
}

const thisEvening = () => {
  const evening = at(0, EVENING_HOUR);
  return evening.getTime() > Date.now() ? evening : at(1, EVENING_HOUR);
};
const QUICK_TIMES: readonly { key: StringKey; when: () => Date }[] = [
  { key: "reminders.quick.hour", when: () => new Date(Date.now() + 60 * MINUTE) },
  { key: "reminders.quick.evening", when: thisEvening },
  { key: "reminders.quick.tomorrow", when: () => at(1, MORNING_HOUR) },
  { key: "reminders.quick.week", when: () => at(WEEK_DAYS, MORNING_HOUR) },
];

function bucket(when: string): StringKey {
  const date = new Date(when);
  if (date.getTime() < Date.now()) return "reminders.group.past";
  const day = date.toDateString();
  if (day === new Date().toDateString()) return "reminders.group.today";
  if (day === at(1, 0).toDateString()) return "reminders.group.tomorrow";
  if (date.getTime() < at(WEEK_DAYS, 0).getTime()) return "reminders.group.week";
  return "reminders.group.later";
}
const ORDER: readonly StringKey[] = ["reminders.group.past", "reminders.group.today", "reminders.group.tomorrow", "reminders.group.week", "reminders.group.later"];

function ReminderRow({ reminder }: { reminder: Reminder }) {
  const save = useSaveReminder();
  const snooze = useSnooze();
  const remove = useRemoveReminder();
  const clock = useTimeOnly();
  const day = useShortDate();
  const relative = useRelativeTime();
  const [title, setTitle] = useState(reminder.title);
  useEffect(() => setTitle(reminder.title), [reminder.title]);
  const update = (changes: { title?: string; when?: string; repeat?: Repeat; proposed?: boolean }) => save.mutate({ id: reminder.id, title: reminder.title, when: reminder.when, repeat: reminder.repeat, thread: reminder.thread ?? null, task: reminder.task ?? null, proposed: reminder.proposed, ...changes });
  const later = (target: Date) => snooze.mutate({ id: reminder.id, minutes: Math.max(1, Math.round((target.getTime() - Date.now()) / MINUTE)) });
  const sameDay = new Date(reminder.when).toDateString() === new Date().toDateString();
  return (
    <Rise as="li" settle="position">
      <ExpandRow
        testid="reminder"
        label={t("reminders.details", { title: reminder.title })}
        leading={
          <span className="flex w-rail shrink-0 flex-col text-sm tabular-nums">
            <span className="text-ink-primary">{clock(reminder.when)}</span>
            {sameDay ? null : <span className="text-ink-muted">{day(reminder.when)}</span>}
          </span>
        }
        title={reminder.title}
        meta={
          reminder.proposed || reminder.repeat !== "none" ? (
            <span className="flex items-center gap-2">
              {reminder.proposed ? <span className="text-accent-default">{t("tasks.proposed")}</span> : null}
              {reminder.repeat !== "none" ? (
                <span className="flex items-center gap-1">
                  <Icon name="repeat" className="h-3 w-3" />
                  {t(reminder.repeat === "day" ? "reminders.repeat.day" : "reminders.repeat.week")}
                </span>
              ) : null}
            </span>
          ) : undefined
        }
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
          <Field label={t("reminders.when")}>{({ invalid, ...control }) => <Input className="py-1" type="datetime-local" invalid={invalid} value={reminder.when.slice(0, 16)} onChange={(event) => event.target.value && update({ when: event.target.value })} {...control} />}</Field>
          <Field label={t("reminders.repeat")}>{({ id }) => <Select compact id={id} value={reminder.repeat} options={REPEATS} onChange={(repeat) => update({ repeat: repeat as Repeat })} />}</Field>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p data-testid="reminder-times" className="text-sm tabular-nums text-ink-muted">
            {reminder.created ? t(reminder.source === "agent" ? "tasks.addedByAgent" : "tasks.added", { when: relative(reminder.created) }) : ""}
            {reminder.updated && reminder.updated !== reminder.created ? ` · ${t("tasks.changed", { when: relative(reminder.updated) })}` : ""}
          </p>
          <div className="flex items-center gap-1">
            {reminder.thread ? <TextLink className="mr-2 text-sm" href={`/mail/all/${reminder.thread}`}>{t("channel.openSource")}</TextLink> : null}
            <IconButton icon="trash" label={t("tasks.remove", { title: reminder.title })} onClick={() => remove.mutate(reminder.id)} />
          </div>
        </div>
      </ExpandRow>
    </Rise>
  );
}

export function RemindersScreen() {
  const reminders = useReminders();
  const save = useSaveReminder();
  const [title, setTitle] = useState("");
  const [when, setWhen] = useState("");
  const [repeat, setRepeat] = useState<Repeat>("none");
  const rows = [...(reminders.data?.reminders ?? [])].sort((a, b) => a.when.localeCompare(b.when));
  const groups = ORDER.map((key) => ({ key, rows: rows.filter((row) => bucket(row.when) === key) })).filter((group) => group.rows.length);
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-5 p-6">
      <PageHeader title={t("nav.reminders")} summary={reminders.data ? tn("reminders.summary", rows.length) : undefined} />
      <form
        className="flex flex-col gap-2 rounded-lg border border-line-subtle bg-surface-raised p-3 transition-colors duration-fast focus-within:border-line-strong"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate({ title: title.trim(), when, repeat }, { onSuccess: () => { setTitle(""); setWhen(""); setRepeat("none"); } });
        }}
      >
        <BareInput aria-label={t("reminders.what")} placeholder={t("reminders.what.placeholder")} value={title} onChange={(event) => setTitle(event.target.value)} className="bg-transparent px-1 py-1 text-md text-ink-primary outline-none placeholder:text-ink-muted" />
        <div className="flex flex-wrap items-center gap-2">
          {QUICK_TIMES.map(({ key, when: pick }) => {
            const value = local(pick());
            return (
              <Pressable key={key} type="button" aria-pressed={when === value} onClick={() => setWhen(value)} className={`focus-ring rounded-full border px-3 py-1 text-sm transition-colors duration-fast ${when === value ? "border-accent-default text-accent-default" : "border-line-subtle text-ink-secondary hover:border-line-strong hover:text-ink-primary"}`}>
                {t(key)}
              </Pressable>
            );
          })}
          <BareInput aria-label={t("reminders.when")} type="datetime-local" value={when} onChange={(event) => setWhen(event.target.value)} className="focus-ring rounded-md bg-transparent px-1 py-1 text-sm text-ink-secondary" />
          <div className="ml-auto flex items-center gap-2">
            <Select quiet label={t("reminders.repeat")} value={repeat} options={REPEATS} onChange={(value) => setRepeat(value as Repeat)} />
            <Button type="submit" variant="primary" loading={save.isPending} disabled={!title.trim() || !when}>
              {t("reminders.add")}
            </Button>
          </div>
        </div>
      </form>
      {reminders.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {reminders.isError ? <ErrorState title={t("reminders.error")} onRetry={() => void reminders.refetch()} /> : null}
      {reminders.isSuccess && rows.length === 0 ? <EmptyState icon="reminders" title={t("reminders.empty")} /> : null}
      <div className="flex flex-col gap-5">
        {groups.map((group) => (
          <section key={group.key} aria-label={t(group.key)} className="flex flex-col gap-2">
            <h2 className={`text-sm ${group.key === "reminders.group.past" ? "text-accent-default" : "text-ink-muted"}`}>{t(group.key)}</h2>
            <ul aria-label={t(group.key)} className="flex flex-col gap-2">
              <Presence>
                {group.rows.map((reminder) => (
                  <ReminderRow key={reminder.id} reminder={reminder} />
                ))}
              </Presence>
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
