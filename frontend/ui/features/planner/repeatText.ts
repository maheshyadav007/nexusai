import type { Reminder } from "@/ui/client/contracts.generated";
import { t, type StringKey } from "../../strings";

const HOUR_MINUTES = 60;
const WEEKDAYS = [0, 1, 2, 3, 4];
const WEEKENDS = [5, 6];
const same = (a: readonly number[], b: readonly number[]) => a.length === b.length && a.every((day, i) => day === b[i]);

/** How a reminder repeats, in words: "Every hour, 10:00–20:00, Mon–Fri, until 31 Dec". */
export function repeatText(reminder: Reminder, day: (value: string) => string): string {
  if (reminder.repeat !== "interval") return t(`reminders.repeat.${reminder.repeat}` as StringKey);
  const minutes = reminder.every_minutes ?? HOUR_MINUTES;
  const parts = [
    minutes === HOUR_MINUTES
      ? t("reminders.repeat.interval.hour")
      : minutes % HOUR_MINUTES === 0
        ? t("reminders.repeat.interval.hours", { count: minutes / HOUR_MINUTES })
        : t("reminders.repeat.interval.minutes", { count: minutes }),
  ];
  if (reminder.window_start && reminder.window_end) parts.push(t("reminders.repeat.window", { start: reminder.window_start, end: reminder.window_end }));
  const days = reminder.days ?? [];
  if (days.length) parts.push(same(days, WEEKDAYS) ? t("reminders.repeat.days.weekdays") : same(days, WEEKENDS) ? t("reminders.repeat.days.weekends") : days.map((d) => t(`reminders.day.${d}` as StringKey)).join(t("rules.said.and")));
  if (reminder.until) parts.push(t("reminders.repeat.until", { date: day(reminder.until) }));
  return parts.join(t("reminders.repeat.join"));
}
