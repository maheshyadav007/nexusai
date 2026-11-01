"use client";

import { useSettings } from "./settings";

const DATE_ORDER: Readonly<Record<string, string>> = { "day-month": "en-GB", "month-day": "en-US", iso: "sv-SE" };

/** A day with no time attached, like a task's due date. It's read as local, not UTC. */
export function useDateOnly(): (value: string) => string {
  const { data } = useSettings();
  const formatter = new Intl.DateTimeFormat(DATE_ORDER[data?.date_format ?? "system"], { dateStyle: "medium" });
  return (value) => {
    const date = new Date(`${value}T00:00`);
    return Number.isNaN(date.getTime()) ? value : formatter.format(date);
  };
}

/** Dates and times in the person's chosen format. */
export function useDateTime(): (value: string) => string {
  const { data } = useSettings();
  const locale = DATE_ORDER[data?.date_format ?? "system"];
  const time = data?.time_format ?? "system";
  const formatter = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    ...(time === "system" ? {} : { hour12: time === "12" }),
  });
  return (value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : formatter.format(date);
  };
}
