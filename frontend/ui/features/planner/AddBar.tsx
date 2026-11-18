"use client";

import { useState, type ReactNode } from "react";
import type { Reminder } from "@/ui/client/contracts.generated";
import { useDateOnly, useShortDate, useTimeOnly } from "@/ui/client/format";
import { Icon, type IconName } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Popover } from "@/ui/primitives/Popover";
import { BareInput, Pressable } from "@/ui/primitives/Pressable";
import { Select } from "@/ui/primitives/Select";
import { t, type StringKey } from "@/ui/strings";

const MINUTE = 60_000;
const EVENING_HOUR = 18;
const MORNING_HOUR = 9;
const WEEK_DAYS = 7;

/** A moment as a time field and the backend take it, in local time. */
export const localMoment = (date: Date) => new Date(date.getTime() - date.getTimezoneOffset() * MINUTE).toISOString().slice(0, 16);
/** A day as yyyy-mm-dd, in local time. */
export const localDay = (date: Date) => date.toLocaleDateString("sv-SE");

export function dayAt(daysAhead: number, hour = 0): Date {
  const date = new Date();
  date.setDate(date.getDate() + daysAhead);
  date.setHours(hour, 0, 0, 0);
  return date;
}

const thisEvening = () => {
  const evening = dayAt(0, EVENING_HOUR);
  return evening.getTime() > Date.now() ? evening : dayAt(1, EVENING_HOUR);
};

/** The moments offered first, for a reminder and for snoozing one. */
export const QUICK_TIMES: readonly { key: StringKey; when: () => Date }[] = [
  { key: "reminders.quick.hour", when: () => new Date(Date.now() + 60 * MINUTE) },
  { key: "reminders.quick.evening", when: thisEvening },
  { key: "reminders.quick.tomorrow", when: () => dayAt(1, MORNING_HOUR) },
  { key: "reminders.quick.week", when: () => dayAt(WEEK_DAYS, MORNING_HOUR) },
];

const QUICK_DAYS: readonly { key: StringKey; day: () => string | null }[] = [
  { key: "tasks.quick.today", day: () => localDay(new Date()) },
  { key: "tasks.quick.tomorrow", day: () => localDay(dayAt(1)) },
  { key: "tasks.quick.week", day: () => localDay(dayAt(WEEK_DAYS)) },
  { key: "tasks.quick.none", day: () => null },
];

export const REPEATS = [
  { value: "none", label: t("reminders.repeat.none") },
  { value: "day", label: t("reminders.repeat.day") },
  { value: "week", label: t("reminders.repeat.week") },
  { value: "month", label: t("reminders.repeat.month") },
  { value: "year", label: t("reminders.repeat.year") },
];

/** One line to add something: an icon, what it is, one quiet button for when, and Add. */
export function AddBar({ label, placeholder, icon, value, onChange, onSubmit, pending, ready, picker }: { label: string; placeholder: string; icon: IconName; value: string; onChange: (value: string) => void; onSubmit: () => void; pending: boolean; ready: boolean; picker: ReactNode }) {
  return (
    <form
      data-testid="add-bar"
      className="flex items-center gap-3 rounded-lg border border-line-subtle bg-surface-raised py-2 pl-4 pr-2 shadow-raised transition-colors duration-fast focus-within:border-line-strong"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) onSubmit();
      }}
    >
      <Icon name={icon} className="h-4 w-4 shrink-0 text-ink-muted" />
      <BareInput aria-label={label} placeholder={placeholder} value={value} onChange={(event) => onChange(event.target.value)} className="min-w-0 flex-1 py-1 text-md outline-none" />
      {picker}
      <Button type="submit" variant="primary" loading={pending} disabled={!ready}>{t("planner.add")}</Button>
    </form>
  );
}

function Option({ label, detail, picked, onPick }: { label: string; detail?: string; picked?: boolean; onPick: () => void }) {
  return (
    <Pressable onClick={onPick} aria-pressed={picked} className={`focus-ring flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-md text-ink-primary transition-colors duration-fast hover:bg-surface-sunken ${picked ? "bg-surface-sunken" : ""}`}>
      <span className="flex-1">{label}</span>
      {detail ? <span className="text-sm tabular-nums text-ink-muted">{detail}</span> : null}
    </Pressable>
  );
}

/** When a task is due: a few days to tap, or any day. No date is a choice too. */
export function DuePicker({ value, onChange }: { value: string | null; onChange: (day: string | null) => void }) {
  const [open, setOpen] = useState(false);
  const formatDay = useDateOnly();
  const weekday = (day: string) => new Date(`${day}T12:00`).toLocaleDateString(undefined, { weekday: "short" });
  const pick = (day: string | null) => {
    onChange(day);
    setOpen(false);
  };
  const trigger = (
    <Button type="button" variant="quiet" aria-label={`${value ? formatDay(value) : t("tasks.quick.none")}, ${t("tasks.changeDue")}`}>
      <Icon name="date" className="h-4 w-4" />
      {value ? formatDay(value) : t("tasks.quick.none")}
    </Button>
  );
  return (
    <Popover label={t("tasks.due")} trigger={trigger} open={open} onOpenChange={setOpen}>
      <div className="-m-2 flex flex-col">
        {QUICK_DAYS.map(({ key, day }) => {
          const shown = day();
          return <Option key={key} label={t(key)} {...(shown ? { detail: weekday(shown) } : {})} picked={shown === value} onPick={() => pick(shown)} />;
        })}
        <div className="mx-3 my-2 h-px bg-line-subtle" />
        <div className="px-3 pb-2">
          <Field label={t("tasks.anyDay")}>{({ invalid, ...control }) => <Input type="date" invalid={invalid} value={value ?? ""} onChange={(event) => pick(event.target.value || null)} {...control} />}</Field>
        </div>
      </div>
    </Popover>
  );
}

/** When a reminder goes off, and whether it repeats: a few moments to tap, or a day and time. */
export function WhenPicker({ value, repeat, onChange, onRepeat }: { value: string; repeat: Reminder["repeat"]; onChange: (when: string) => void; onRepeat: (repeat: Reminder["repeat"]) => void }) {
  const [open, setOpen] = useState(false);
  const clock = useTimeOnly();
  const day = useShortDate();
  const label = value ? `${new Date(value).toDateString() === new Date().toDateString() ? t("reminders.group.today") : day(value)}, ${clock(value)}` : t("reminders.pickWhen");
  const [date, time] = value ? value.split("T") : ["", ""];
  const trigger = (
    <Button type="button" variant="quiet" aria-label={`${label}, ${t("reminders.changeWhen")}`}>
      <Icon name={repeat === "none" ? "time" : "repeat"} className="h-4 w-4" />
      {label}
    </Button>
  );
  return (
    <Popover label={t("reminders.when")} trigger={trigger} open={open} onOpenChange={setOpen}>
      <div className="-m-2 flex flex-col">
        {QUICK_TIMES.map(({ key, when }) => {
          const moment = when();
          return <Option key={key} label={t(key)} detail={clock(localMoment(moment))} picked={localMoment(moment) === value} onPick={() => { onChange(localMoment(moment)); setOpen(false); }} />;
        })}
        <div className="mx-3 my-2 h-px bg-line-subtle" />
        <div className="grid grid-cols-2 gap-2 px-3">
          <Field label={t("reminders.day")}>{({ invalid, ...control }) => <Input type="date" invalid={invalid} value={date ?? ""} onChange={(event) => event.target.value && onChange(`${event.target.value}T${time || "09:00"}`)} {...control} />}</Field>
          <Field label={t("reminders.time")}>{({ invalid, ...control }) => <Input type="time" invalid={invalid} value={time ?? ""} onChange={(event) => event.target.value && onChange(`${date || localDay(new Date())}T${event.target.value}`)} {...control} />}</Field>
        </div>
        <div className="px-3 pb-2 pt-2">
          <Field label={t("reminders.repeat")}>{({ id }) => <Select compact id={id} value={repeat} options={REPEATS} onChange={(next) => onRepeat(next as Reminder["repeat"])} />}</Field>
        </div>
      </div>
    </Popover>
  );
}
