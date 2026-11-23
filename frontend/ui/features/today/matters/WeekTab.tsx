"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { MatterLane, MatterMark } from "@/ui/client/contracts.generated";
import { useDateOnly, useDateTime, useTimeOnly } from "@/ui/client/format";
import { useMattersWeek } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Pressable } from "@/ui/primitives/Pressable";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { CountGlyph, MarkGlyph, Track, TrackCluster, TrackMark, TrackNow, TrackSpan, type MarkShape, type MarkTone } from "@/ui/primitives/Track";
import light from "@/ui/theme/themes/nexus-light.json";
import { t, type StringKey } from "@/ui/strings";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { useMatterActions } from "./matterActions";
import { StateText, placeIn, useTodayView, type MatterMarkKind } from "./parts";

const WEEK = 7;
// It opens on last week, this week and next, and grows a week at a time at either edge.
const FIRST_WEEKS = 3;
// Half a year at most, the most the server gives at once.
const MOST_DAYS = 182;
// This close to an edge, the next week loads.
const EDGE = 0.5;
const DAY_PX = Number.parseFloat(light.layout.day);
const MARKS: Record<MatterMarkKind, { shape: MarkShape; tone: MarkTone }> = {
  in: { shape: "dot", tone: "ink" },
  sent: { shape: "ring", tone: "ink" },
  due: { shape: "diamond", tone: "warning" },
  reminder: { shape: "diamondRing", tone: "warning" },
  closed: { shape: "dot", tone: "success" },
  reopened: { shape: "ring", tone: "success" },
  step: { shape: "ring", tone: "muted" },
};

// Marks closer than this many pixels sit on each other, so they show as one numbered mark.
const APART_PX = 20;

/** The marks, in order, grouped where they'd overlap: each group is their indexes. */
function closeTogether(points: readonly number[], days: number): number[][] {
  const groups: number[][] = [];
  points.forEach((at, index) => {
    const group = groups.at(-1);
    const start = group ? (points[group[0] as number] ?? 0) : 0;
    if (group && (at - start) * days * DAY_PX < APART_PX) group.push(index);
    else groups.push([index]);
  });
  return groups;
}

function mondayOf(date: Date): Date {
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  day.setDate(day.getDate() - ((day.getDay() + 6) % 7));
  return day;
}

const plus = (date: Date, days: number) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
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

/** As many day columns as are loaded. The count is data, so it's a CSS variable. */
function useDayCount<T extends HTMLElement>(days: number) {
  const ref = useRef<T>(null);
  useLayoutEffect(() => ref.current?.style.setProperty("--nx-days", String(days)), [days]);
  return ref;
}

function Lane({ lane, start, days, now }: { lane: MatterLane; start: Date; days: number; now: number }) {
  const { go } = useTodayView();
  const moment = useDateTime();
  const day = useDateOnly();
  const clock = useTimeOnly();
  const strip = useDayCount<HTMLDivElement>(days);
  const matter = lane.matter;
  const actions = useMatterActions(matter);
  const nowAt = (now - start.getTime()) / (days * 86_400_000);
  const points = lane.marks.map((mark) => placeIn(mark.time, start, days));
  const open = matter.state !== "done";
  const from = Math.min(...points, open ? nowAt : 1);
  const to = open ? Math.max(...points, Math.min(nowAt, 1)) : Math.max(...points);
  // A step says what it was; every other mark is named by its kind.
  const what = (mark: MatterMark) => (mark.kind === "step" ? mark.label : `${t(`matters.week.mark.${mark.kind}` as StringKey)}: ${mark.label}`);
  const label = (mark: MatterMark) => `${mark.time.length > 10 ? moment(mark.time) : day(mark.time)} · ${what(mark)}`;
  const overdue = (mark: MatterMark) => open && mark.kind === "due" && new Date(mark.time.length > 10 ? mark.time : `${mark.time}T23:59`).getTime() < now;
  const today = Math.floor(nowAt * days);
  return (
    <li data-testid="week-lane" className="flex items-stretch border-t border-line-subtle">
      {/* Stays put while the days scroll under it, so each line keeps its name. */}
      <ContextMenu items={actions}>
      <div className="sticky left-0 z-raised flex w-sidebar shrink-0 items-center border-r border-line-subtle bg-surface-raised pr-2">
        <Pressable onClick={() => go("matters", matter.id)} className="flex min-w-0 flex-1 flex-col items-start gap-1 py-3 pl-4 pr-2 text-left">
          <span className="w-full truncate text-md font-medium text-ink-primary transition-colors duration-fast hover:text-accent-default">{matter.title}</span>
          <StateText state={matter.state} />
        </Pressable>
      </div>
      </ContextMenu>
      <div ref={strip} className="nx-days relative">
        {Array.from({ length: days }, (_, index) => <span key={index} aria-hidden className={`border-l border-line-subtle ${today === index ? "bg-accent-default/5" : ""}`} />)}
        <span className="absolute inset-x-0 top-1/2 -translate-y-1/2"><Track>
          {points.length ? <TrackSpan from={from} to={to} strong={matter.state === "waiting_on_you"} /> : null}
          {nowAt >= 0 && nowAt <= 1 ? <TrackNow at={nowAt} /> : null}
          {closeTogether(points, days).map((group) => {
            const first = group[0] as number;
            const last = lane.marks[group.at(-1) as number] as MatterMark;
            const tone = (mark: MatterMark) => (overdue(mark) ? "danger" : MARKS[mark.kind].tone);
            if (group.length === 1) {
              const look = MARKS[last.kind];
              return <TrackMark key={`${last.time}-${first}`} at={points[first] ?? 0} shape={look.shape} tone={tone(last)} label={label(last)} />;
            }
            const marks = group.map((index) => lane.marks[index] as MatterMark);
            return <TrackCluster key={`${last.time}-${first}`} at={points[first] ?? 0} tone={tone(last)}
              title={t("matters.week.steps", { day: day(marks[0]?.time ?? last.time), count: marks.length })}
              steps={marks.map((mark) => ({ when: mark.time.length > 10 ? clock(mark.time) : "", what: what(mark) }))} />;
          })}
        </Track></span>
      </div>
    </li>
  );
}

/** Every matter as one line through the days, with each email, reply, due date and close on it.
 * The names stay; the days scroll sideways, and more load at either end. */
export function WeekTab() {
  const [range, setRange] = useState(() => ({ start: plus(mondayOf(new Date()), -WEEK), days: FIRST_WEEKS * WEEK }));
  const week = useMattersWeek(isoDay(range.start), range.days);
  const now = useNow();
  const day = useDateOnly();
  const scroller = useRef<HTMLElement>(null);
  const header = useDayCount<HTMLDivElement>(range.days);
  // Days added on the left push what's in view right; this puts it back.
  const shift = useRef(0);
  const short = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric" });
  const month = new Intl.DateTimeFormat(undefined, { month: "short" });
  const days = Array.from({ length: range.days }, (_, index) => plus(range.start, index));
  const today = isoDay(new Date());
  const lanes = week.data?.lanes ?? [];

  const toDay = (date: Date, behavior: ScrollBehavior = "smooth") => {
    const node = scroller.current;
    if (!node) return;
    const index = Math.round((date.getTime() - range.start.getTime()) / 86_400_000);
    node.scrollTo({ left: Math.max(index * DAY_PX, 0), behavior });
  };
  // Opens on this week.
  const placed = useRef(false);
  useLayoutEffect(() => {
    if (placed.current || !scroller.current) return;
    placed.current = true;
    toDay(mondayOf(new Date()), "auto");
  });
  useLayoutEffect(() => {
    if (!shift.current || !scroller.current) return;
    scroller.current.scrollLeft += shift.current;
    shift.current = 0;
  }, [range.start]);

  const onScroll = () => {
    const node = scroller.current;
    if (!node || range.days >= MOST_DAYS) return;
    const edge = WEEK * DAY_PX * EDGE;
    if (node.scrollLeft < edge) {
      shift.current = WEEK * DAY_PX;
      setRange((current) => ({ start: plus(current.start, -WEEK), days: current.days + WEEK }));
    } else if (node.scrollWidth - node.clientWidth - node.scrollLeft < edge) {
      setRange((current) => ({ ...current, days: current.days + WEEK }));
    }
  };
  const byWeek = (weeks: number) => scroller.current?.scrollBy({ left: weeks * WEEK * DAY_PX, behavior: "smooth" });

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 className="text-lg font-medium text-ink-primary">{t("matters.week.title")}</h2>
          <p className="text-sm text-ink-muted">{t("matters.week.hint")}</p>
        </div>
        <div className="flex items-center gap-1">
          <IconButton icon="chevronLeft" label={t("matters.week.previous")} onClick={() => byWeek(-1)} />
          <Button variant="quiet" onClick={() => toDay(mondayOf(new Date()))}>{t("matters.week.this")}</Button>
          <IconButton icon="chevronRight" label={t("matters.week.next")} onClick={() => byWeek(1)} />
        </div>
      </header>
      {week.isError ? <ErrorState title={t("matters.error")} onRetry={() => void week.refetch()} /> : null}
      <section ref={scroller} onScroll={onScroll} aria-label={t("matters.week.range", { from: day(isoDay(range.start)), to: day(isoDay(plus(range.start, range.days - 1))) })} className="overflow-x-auto overscroll-x-contain rounded-lg border border-line-subtle bg-surface-raised pb-2 shadow-raised">
        <div className="min-w-max">
          <div className="flex">
            <span className="sticky left-0 z-raised w-sidebar shrink-0 border-r border-line-subtle bg-surface-raised" />
            <div ref={header} className="nx-days">
              {days.map((date) => {
                const isToday = isoDay(date) === today;
                // Each week says its month, so it's known wherever the strip is scrolled to.
                const first = date.getDay() === 1 || date.getDate() === 1;
                return (
                  <span key={isoDay(date)} className={`flex flex-col items-center py-2 text-sm tabular-nums ${date.getDay() === 1 ? "border-l border-line-subtle" : ""} ${isToday ? "font-medium text-accent-default" : "text-ink-muted"}`}>
                    <span className="text-ink-muted">{first ? month.format(date) : "\u00A0"}</span>
                    {short.format(date)}
                  </span>
                );
              })}
            </div>
          </div>
          {week.isPending ? <Skeleton className="mx-4 mb-3 h-12" /> : null}
          <ul>{lanes.map((lane) => <Lane key={lane.matter.id} lane={lane} start={range.start} days={range.days} now={now} />)}</ul>
        </div>
      </section>
      {week.isSuccess && lanes.length === 0 ? <EmptyState icon="calendar" title={t("matters.week.empty")} /> : null}
      <section aria-label={t("matters.week.key")} className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-ink-secondary">
        {(Object.keys(MARKS) as MatterMarkKind[]).map((kind) => (
          <span key={kind} className="flex items-center gap-2"><MarkGlyph {...MARKS[kind]} />{t(`matters.week.mark.${kind}` as StringKey)}</span>
        ))}
        <span className="flex items-center gap-2"><CountGlyph count={3} tone="ink" />{t("matters.week.mark.many")}</span>
        <span className="flex items-center gap-2"><span aria-hidden className="h-3 w-px bg-accent-default" />{t("matters.week.mark.now")}</span>
      </section>
    </div>
  );
}
