"use client";

import { useState } from "react";
import { useDateTime } from "@/ui/client/format";
import { useReminders, useRemoveReminder, useSaveReminder, useSnooze } from "@/ui/client/work";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { TextLink } from "@/ui/primitives/TextLink";
import { t } from "@/ui/strings";

const REPEATS = [
  { value: "none", label: t("reminders.repeat.none") },
  { value: "day", label: t("reminders.repeat.day") },
  { value: "week", label: t("reminders.repeat.week") },
];
const SNOOZE_MINUTES = 60;

export function RemindersScreen() {
  const reminders = useReminders();
  const save = useSaveReminder();
  const snooze = useSnooze();
  const remove = useRemoveReminder();
  const format = useDateTime();
  const [title, setTitle] = useState("");
  const [when, setWhen] = useState("");
  const [repeat, setRepeat] = useState("none");
  const rows = reminders.data?.reminders ?? [];
  return (
    <div className="mx-auto flex max-w-content flex-col gap-4 p-6">
      <h1 className="font-serif text-display text-ink-primary">{t("nav.reminders")}</h1>
      <form
        className="grid items-end gap-2 md:grid-cols-4"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate({ title: title.trim(), when, repeat: repeat as "none" | "day" | "week" }, { onSuccess: () => { setTitle(""); setWhen(""); } });
        }}
      >
        <Field label={t("reminders.what")}>{({ invalid, ...control }) => <Input invalid={invalid} value={title} onChange={(event) => setTitle(event.target.value)} {...control} />}</Field>
        <Field label={t("reminders.when")}>{({ invalid, ...control }) => <Input type="datetime-local" invalid={invalid} value={when} onChange={(event) => setWhen(event.target.value)} {...control} />}</Field>
        <Field label={t("reminders.repeat")}>{({ invalid, id }) => <Select id={id} invalid={invalid} value={repeat} options={REPEATS} onChange={setRepeat} />}</Field>
        <Button type="submit" variant="primary" loading={save.isPending} disabled={!title.trim() || !when}>{t("reminders.add")}</Button>
      </form>
      {reminders.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {reminders.isError ? <ErrorState title={t("reminders.error")} onRetry={() => void reminders.refetch()} /> : null}
      {reminders.isSuccess && rows.length === 0 ? <EmptyState icon="reminders" title={t("reminders.empty")} /> : null}
      <ul aria-label={t("nav.reminders")} className="flex flex-col gap-2">
        {rows.map((reminder) => (
          <li key={reminder.id} data-testid="reminder" className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line-subtle p-3">
            <span className="min-w-0">
              <span className="block text-md text-ink-primary">{reminder.title}</span>
              <span className="text-sm tabular-nums text-ink-muted">{format(reminder.when)}</span>
            </span>
            <span className="flex items-center gap-2">
              {reminder.thread ? <TextLink className="text-sm" href={`/mail/all/${reminder.thread}`}>{t("channel.openSource")}</TextLink> : null}
              {reminder.proposed ? (
                <>
                  <Badge tone="accent">{t("tasks.proposed")}</Badge>
                  <Button variant="primary" onClick={() => save.mutate({ id: reminder.id, title: reminder.title, when: reminder.when, repeat: reminder.repeat, thread: reminder.thread ?? null, task: reminder.task ?? null, proposed: false })}>{t("tasks.accept")}</Button>
                </>
              ) : (
                <Button onClick={() => snooze.mutate({ id: reminder.id, minutes: SNOOZE_MINUTES })}>{t("reminders.snooze")}</Button>
              )}
              <IconButton icon="close" label={t("tasks.remove", { title: reminder.title })} onClick={() => remove.mutate(reminder.id)} />
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
