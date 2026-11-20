"use client";

import { useEffect, useState } from "react";
import type { MatterLane, MatterMark } from "@/ui/client/contracts.generated";
import { useDateOnly, useDateTime } from "@/ui/client/format";
import { useMattersWeek } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Pressable } from "@/ui/primitives/Pressable";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { MarkGlyph, Track, TrackMark, TrackNow, TrackSpan, type MarkShape, type MarkTone } from "@/ui/primitives/Track";
import { t, type StringKey } from "@/ui/strings";
import { StateText, placeIn, useTodayView, type MatterMarkKind } from "./parts";

const DAYS = 7;
const MARKS: Record<MatterMarkKind, { shape: MarkShape; tone: MarkTone }> = {
  in: { shape: "dot", tone: "ink" },
  sent: { shape: "ring", tone: "ink" },
  due: { shape: "diamond", tone: "warning" },
  reminder: { shape: "diamondRing", tone: "warning" },
  closed: { shape: "dot", tone: "success" },
};

function mondayOf(date: Date): Date {
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  day.setDate(day.getDate() - ((day.getDay() + 6) % 7));
  return day;
}

const isoDay = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

/** A minute is enough for the line that marks now. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

function Lane({ lane, start, now }: { lane: MatterLane; start: Date; now: number }) {
  const { go } = useTodayView();
  const moment = useDateTime();
  const day = useDateOnly();
  const matter = lane.matter;
  const nowAt = (now - start.getTime()) / (DAYS * 86_400_000);
  const points = lane.marks.map((mark) => placeIn(mark.time, start, DAYS));
  const open = matter.state !== "done";
  const from = Math.min(...points, open ? nowAt : 1);
  const to = open ? Math.max(...points, Math.min(nowAt, 1)) : Math.max(...points);
  const label = (mark: MatterMark) => `${mark.time.length > 10 ? moment(mark.time) : day(mark.time)} · ${t(`matters.week.mark.${mark.kind}` as StringKey)}: ${mark.label}`;
  const overdue = (mark: MatterMark) => open && mark.kind === "due" && new Date(mark.time.length > 10 ? mark.time : `${mark.time}T23:59`).getTime() < now;
  return (
    <li data-testid="week-lane" className="grid grid-cols-lane items-center border-t border-line-subtle">
      <Pressable onClick={() => go("matters", matter.id)} className="flex min-w-0 flex-col items-start gap-1 rounded-sm py-3 pr-4 text-left">
        <span className="w-full truncate text-md font-medium text-ink-primary transition-colors duration-fast hover:text-accent-default">{matter.title}</span>
        <StateText state={matter.state} />
      </Pressable>
      <Track className="h-7">
        <span aria-hidden className="absolute inset-0 grid grid-cols-week">
          {Array.from({ length: DAYS }, (_, index) => <span key={index} className={`border-l border-line-subtle ${Math.floor(nowAt * DAYS) === index ? "bg-accent-default/5" : ""}`} />)}
        </span>
        {points.length ? <TrackSpan from={from} to={to} strong={matter.state === "waiting_on_you"} /> : null}
        {nowAt >= 0 && nowAt <= 1 ? <TrackNow at={nowAt} /> : null}
        {lane.marks.map((mark, index) => {
          const look = MARKS[mark.kind];
          return <TrackMark key={`${mark.time}-${index}`} at={points[index] ?? 0} shape={look.shape} tone={overdue(mark) ? "danger" : look.tone} label={label(mark)} />;
        })}
      </Track>
    </li>
  );
}

/** The week as one line per matter, with every email, reply, due date and close on it. */
export function WeekTab() {
  const [start, setStart] = useState(() => mondayOf(new Date()));
  const week = useMattersWeek(isoDay(start));
  const now = useNow();
  const day = useDateOnly();
  const short = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric" });
  const move = (weeks: number) => setStart((current) => new Date(current.getFullYear(), current.getMonth(), current.getDate() + weeks * DAYS));
  const thisWeek = isoDay(start) === isoDay(mondayOf(new Date()));
  const days = Array.from({ length: DAYS }, (_, index) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + index));
  const today = isoDay(new Date());
  const lanes = week.data?.lanes ?? [];
  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 className="text-lg font-medium text-ink-primary">{t("matters.week.label", { when: day(isoDay(start)) })}</h2>
          <p className="text-sm text-ink-muted">{t("matters.week.hint")}</p>
        </div>
        <div className="flex items-center gap-1">
          <IconButton icon="chevronLeft" label={t("matters.week.previous")} onClick={() => move(-1)} />
          <Button variant="quiet" disabled={thisWeek} onClick={() => setStart(mondayOf(new Date()))}>{t("matters.week.this")}</Button>
          <IconButton icon="chevronRight" label={t("matters.week.next")} onClick={() => move(1)} />
        </div>
      </header>
      {week.isError ? <ErrorState title={t("matters.error")} onRetry={() => void week.refetch()} /> : null}
      <section aria-label={t("matters.week.label", { when: day(isoDay(start)) })} className="overflow-x-auto rounded-lg border border-line-subtle bg-surface-raised px-4 pb-2 shadow-raised">
        <div className="min-w-content">
          <div className="grid grid-cols-lane">
            <span />
            <span className="grid grid-cols-week">
              {days.map((date) => {
                const isToday = isoDay(date) === today;
                return <span key={isoDay(date)} className={`py-3 text-center text-sm tabular-nums ${isToday ? "font-medium text-accent-default" : "text-ink-muted"}`}>{short.format(date)}</span>;
              })}
            </span>
          </div>
          {week.isPending ? <Skeleton className="mb-3 h-12 w-full" /> : null}
          {week.isSuccess && lanes.length === 0 ? <div className="border-t border-line-subtle py-6"><EmptyState icon="calendar" title={t("matters.week.empty")} /></div> : null}
          <ul>{lanes.map((lane) => <Lane key={lane.matter.id} lane={lane} start={start} now={now} />)}</ul>
        </div>
      </section>
      <section aria-label={t("matters.week.key")} className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-ink-secondary">
        {(Object.keys(MARKS) as MatterMarkKind[]).map((kind) => (
          <span key={kind} className="flex items-center gap-2"><MarkGlyph {...MARKS[kind]} />{t(`matters.week.mark.${kind}` as StringKey)}</span>
        ))}
        <span className="flex items-center gap-2"><span aria-hidden className="h-3 w-px bg-accent-default" />{t("matters.week.mark.now")}</span>
      </section>
    </div>
  );
}
