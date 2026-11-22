"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { query } from "@/ui/client/api";
import type { MatterChange, MatterDetail, MatterRow, MatterWork } from "@/ui/client/contracts.generated";
import { useDateOnly, useShortDate, useTimeOnly } from "@/ui/client/format";
import { useMatter, useMatterList, useMatterReopen, useMergeMatter, useSaveTask, useTasks, useUnlinkThread, useUnmergeMatter } from "@/ui/client/work";
import { mailSource } from "@/ui/features/sources/kinds";
import { SourceChip } from "@/ui/features/sources/SourceChip";
import { Icon } from "@/ui/icons";
import { Avatar } from "@/ui/primitives/Avatar";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Pressable, RowButton } from "@/ui/primitives/Pressable";
import { Segmented } from "@/ui/primitives/Segmented";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { useToast } from "@/ui/primitives/Toast";
import { MarkGlyph } from "@/ui/primitives/Track";
import { t, tn, type StringKey } from "@/ui/strings";
import { KIND_MARK, StateText, countsOf, kindLabel, useDue, useMatterDoneWithUndo, useTodayView } from "./parts";

function ListItem({ matter, selected, onPick }: { matter: MatterRow; selected: boolean; onPick: () => void }) {
  const due = useDue();
  const when = matter.due ? due(matter.due) : null;
  return (
    <li>
      <RowButton aria-current={selected ? "true" : undefined} onClick={onPick} className={`flex-col items-stretch gap-1 py-3 ${selected ? "bg-surface-sunken" : ""}`}>
        <span className="flex items-baseline justify-between gap-2">
          <span className={`truncate text-md ${selected ? "font-medium text-ink-primary" : "text-ink-primary"}`}>{matter.title}</span>
          {when ? <span className={`shrink-0 text-sm tabular-nums ${when.overdue ? "text-status-danger" : "text-status-warning"}`}>{when.text}</span> : null}
        </span>
        <span className="flex items-center gap-2 text-sm text-ink-muted">
          <StateText state={matter.state} />
          <span aria-hidden>·</span>
          <span className="truncate">{countsOf(matter)}</span>
        </span>
      </RowButton>
    </li>
  );
}

function WorkItem({ item }: { item: MatterWork }) {
  const due = useDue();
  const tasks = useTasks(false);
  const save = useSaveTask();
  const when = item.when ? due(item.when) : null;
  const meta = [t(`matters.work.${item.kind}` as StringKey), when?.text].filter(Boolean).join(" · ");
  if (item.kind === "task") {
    const task = tasks.data?.tasks.find((row) => row.id === item.id);
    return (
      <li className="flex flex-col gap-1">
        <Checkbox label={item.title} checked={false} disabled={!task || save.isPending} onChange={() => task && save.mutate({ id: task.id, title: task.title, notes: task.notes, status: "done", due: task.due ?? null, thread: task.thread ?? null, proposed: false })} />
        <span className={`pl-5 text-sm tabular-nums ${when?.overdue ? "text-status-danger" : "text-ink-muted"}`}>{meta}{item.proposed ? ` · ${t("matters.work.suggested")}` : ""}</span>
      </li>
    );
  }
  return (
    <li className="flex items-start gap-2">
      <Icon name={item.kind === "reminder" ? "reminders" : "date"} className="mt-px h-4 w-4 shrink-0 text-ink-muted" />
      <span className="flex min-w-0 flex-col gap-1">
        <span className="text-md text-ink-primary">{item.title}</span>
        <span className={`text-sm tabular-nums ${when?.overdue ? "text-status-danger" : "text-ink-muted"}`}>{meta}</span>
      </span>
    </li>
  );
}

function WorkList({ work }: { work: readonly MatterWork[] }) {
  const ids = new Set(work.filter((item) => item.kind === "task").map((item) => item.id));
  // A reminder that belongs to a to-do is listed under it: it finishes and moves with it.
  const top = work.filter((item) => !(item.kind === "reminder" && item.parent != null && ids.has(item.parent)));
  return (
    <ul className="flex flex-col gap-3">
      {top.map((item) => {
        const under = item.kind === "task" ? work.filter((child) => child.kind === "reminder" && child.parent === item.id) : [];
        return (
          <li key={`${item.kind}-${item.id}`} className="flex flex-col gap-2">
            <ul className="flex flex-col"><WorkItem item={item} /></ul>
            {under.length ? (
              <ul aria-label={t("matters.work.under")} className="ml-5 flex flex-col gap-2 border-l border-line-subtle pl-3">
                {under.map((child) => <WorkItem key={`reminder-${child.id}`} item={child} />)}
              </ul>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

/** Everything that happened, top to bottom as it happened, in its own scrolling box. It opens at
 *  the newest; scrolling up loads earlier changes until the start. */
function Timeline({ detail }: { detail: MatterDetail }) {
  const dateOnly = useDateOnly();
  const time = useTimeOnly();
  // Each day once, above its changes: "Today", or the date.
  const dayOf = (when: string) => {
    const date = new Date(when);
    if (date.toDateString() === new Date().toDateString()) return t("matters.timeline.today");
    return dateOnly(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`);
  };
  const box = useRef<HTMLOListElement>(null);
  const [earlier, setEarlier] = useState<MatterChange[]>([]);
  const [more, setMore] = useState(detail.earlier);
  const [loading, setLoading] = useState(false);
  const kept = useRef<number | null>(null);
  const events = [...earlier, ...detail.events];
  // A new matter starts at its newest change.
  useEffect(() => {
    setEarlier([]);
    setMore(detail.earlier);
  }, [detail.matter.id]);
  useLayoutEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [detail.matter.id]);
  // Earlier changes go above without moving what's being read.
  useLayoutEffect(() => {
    if (box.current && kept.current !== null) {
      box.current.scrollTop = box.current.scrollHeight - kept.current;
      kept.current = null;
    }
  }, [earlier.length]);
  const loadEarlier = async () => {
    const oldest = events[0];
    if (!more || loading || !oldest) return;
    setLoading(true);
    try {
      const page = await query("matters.events", { id: detail.matter.id, before: oldest.id });
      kept.current = box.current ? box.current.scrollHeight - box.current.scrollTop : null;
      setEarlier((shown) => [...page.events, ...shown]);
      setMore(page.earlier);
    } finally {
      setLoading(false);
    }
  };
  return (
    <section aria-label={t("matters.timeline")} className="flex flex-col gap-3 border-t border-line-subtle pt-4">
      <header className="flex items-baseline justify-between gap-2">
        <h3 className="text-md font-medium text-ink-primary">{t("matters.timeline")}</h3>
        <span className="text-sm text-ink-muted">{t("matters.timeline.newest")}</span>
      </header>
      <ol
        ref={box}
        data-testid="matter-timeline"
        tabIndex={0}
        aria-busy={loading}
        onScroll={(event) => {
          if (event.currentTarget.scrollTop < 48) void loadEarlier();
        }}
        className="category-scroll flex max-h-timeline flex-col overflow-y-auto overscroll-contain pr-2"
      >
        <li className="pb-3 text-sm text-ink-muted">
          {more ? <Button variant="quiet" className="-ml-3 py-px" loading={loading} onClick={() => void loadEarlier()}>{t("matters.timeline.loading")}</Button> : t("matters.timeline.start")}
        </li>
        {events.map((event, index) => {
          const day = new Date(event.time).toDateString();
          const newDay = index === 0 || new Date(events[index - 1]!.time).toDateString() !== day;
          return (
            <li key={event.id} className="flex flex-col">
              {newDay ? <p className="pb-2 pt-1 text-sm font-medium tabular-nums text-ink-secondary">{dayOf(event.time)}</p> : null}
              <div className="grid grid-cols-timeline gap-3">
                <span className="pt-px text-sm tabular-nums text-ink-muted">{time(event.time)}</span>
                <span aria-hidden className="flex flex-col items-center">
                  <span className="pt-1"><MarkGlyph {...KIND_MARK[event.kind]} /></span>
                  {index < events.length - 1 ? <span className="w-px flex-1 bg-line-subtle" /> : null}
                </span>
                <div className="flex min-w-0 flex-col gap-1 pb-4">
                  <p className="text-md text-ink-primary"><span className="font-medium">{kindLabel(event.kind)}</span><span className="text-ink-secondary"> · {event.text}</span></p>
                  {/* Why matters where a conversation joined or left; elsewhere the line says it. */}
                  {event.why && (event.kind === "joined" || event.kind === "moved" || event.kind === "linked") ? <p className="text-sm text-ink-muted">{t("matters.why", { why: event.why })}</p> : null}
                  {event.source ? <div><SourceChip source={event.source} /></div> : null}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** One matter, top to bottom in the order it's needed: what to do next, what's open, what
 * happened. What it's alike, its files, and why its conversations are together come last. */
function Detail({ detail }: { detail: MatterDetail }) {
  const matter = detail.matter;
  const short = useShortDate();
  const due = useDue();
  const finish = useMatterDoneWithUndo();
  const reopen = useMatterReopen();
  const unlink = useUnlinkThread();
  const merge = useMergeMatter();
  const unmerge = useUnmergeMatter();
  const { go } = useTodayView();
  const toast = useToast();
  const [together, setTogether] = useState(false);
  const when = matter.due ? due(matter.due) : null;
  const done = matter.state === "done";
  const people = detail.people.slice(0, 3);
  return (
    <article className="flex min-w-0 max-w-reading flex-col gap-5 rounded-lg border border-line-subtle bg-surface-raised p-5 shadow-raised">
      <header data-testid="matter-header" className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <StateText state={matter.state} />
          <h2 className="font-serif text-title text-ink-primary">{matter.title}</h2>
          {matter.next || when ? (
            <p className="text-md text-ink-secondary">
              {matter.next ? t("matters.next", { next: matter.next }) : null}
              {when ? <span className={`ml-2 tabular-nums ${when.overdue ? "font-medium text-status-danger" : "text-status-warning"}`}>{when.text}</span> : null}
            </p>
          ) : null}
          <p className="flex flex-wrap items-center gap-2 text-sm tabular-nums text-ink-muted">
            {people.length ? <span className="flex items-center gap-1">{people.map((name) => <Avatar key={name} name={name} />)}<span className="ml-1">{[...people, ...(detail.people.length > people.length ? [t("matters.people.more", { count: detail.people.length - people.length })] : [])].join(", ")}</span></span> : null}
            {matter.started ? <span>{t("matters.started", { when: short(matter.started) })}</span> : null}
            <span>{countsOf(matter)}</span>
          </p>
        </div>
        {done ? <Button onClick={() => reopen.mutate(matter.id)} loading={reopen.isPending}>{t("matters.undo")}</Button> : <Button variant="primary" data-testid="matter-done" onClick={() => finish(matter)}>{t("matters.done")}</Button>}
      </header>
      {matter.work?.length ? (
        <section aria-label={t("matters.work")} className="flex flex-col gap-3 border-t border-line-subtle pt-4">
          <h3 className="text-md font-medium text-ink-primary">{t("matters.work")}</h3>
          <WorkList work={matter.work} />
        </section>
      ) : null}
      <Timeline detail={detail} />
      {(detail.related ?? []).length ? (
        <section aria-label={t("matters.related")} className="flex flex-col gap-3 border-t border-line-subtle pt-4">
          <h3 className="text-md font-medium text-ink-primary">{t("matters.related")}</h3>
          <p className="text-sm text-ink-muted">{t("matters.related.hint")}</p>
          <ul className="flex flex-col gap-3">
            {(detail.related ?? []).map((other) => (
              <li key={other.matter} className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex min-w-0 flex-col gap-1">
                  <Pressable onClick={() => go("matters", other.matter)} className="truncate rounded-sm text-left text-md text-ink-primary transition-colors duration-fast hover:text-accent-default">{other.title}</Pressable>
                  <span className="text-sm text-ink-muted">{[t(`matters.state.${other.state}` as StringKey), other.why].filter(Boolean).join(" · ")}</span>
                </span>
                <Button
                  variant="quiet"
                  loading={merge.isPending}
                  onClick={() =>
                    merge.mutate(
                      { id: other.matter, into: matter.id },
                      {
                        onSuccess: () => toast({ title: t("matters.related.merged"), action: { label: t("matters.unmerge"), run: () => unmerge.mutate(other.matter) } }),
                        onError: (error) => toast({ title: error.message, tone: "danger" }),
                      },
                    )
                  }
                >
                  {t("matters.related.merge")}
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {(detail.files ?? []).length ? (
        <section aria-label={t("matters.files")} className="flex flex-col gap-3 border-t border-line-subtle pt-4">
          <h3 className="text-md font-medium text-ink-primary">{t("matters.files")}</h3>
          <ul className="flex flex-col gap-2">
            {(detail.files ?? []).map((file) => (
              <li key={file.ref} className="flex min-w-0 flex-wrap items-center gap-2 text-md text-ink-primary">
                <Icon name="attachment" className="h-4 w-4 shrink-0 text-ink-muted" />
                <span className="min-w-0 truncate">{file.title}</span>
                {file.source ? <SourceChip source={file.source} /> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section aria-label={t("matters.together")} className="flex flex-col gap-3 border-t border-line-subtle pt-4">
        <Button variant="quiet" className="-ml-3 self-start py-px" aria-expanded={together} onClick={() => setTogether(!together)}>{tn("matters.together.fold", detail.threads.length)}</Button>
        {together ? (
          <ul className="flex flex-col gap-3">
            {detail.threads.map((thread) => (
              <li key={thread.id} className="flex flex-col gap-1">
                <SourceChip source={{ ...mailSource(thread.id), title: thread.subject, date: thread.last_date }} />
                <p className="text-sm text-ink-secondary">{thread.how === "start" ? t("matters.together.start") : thread.why}</p>
                {detail.threads.length > 1 && thread.how !== "start" ? (
                  <Button variant="quiet" className="-ml-3 self-start py-px" onClick={() => unlink.mutate(thread.id, { onSuccess: () => toast({ title: t("matters.notPart.done") }) })}>{t("matters.notPart")}</Button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </article>
  );
}

/** Every matter, and the one picked with everything that happened to it. */
export function MattersTab() {
  const [scope, setScope] = useState<"open" | "all">("open");
  const list = useMatterList(scope === "all");
  const { matter: chosen, go } = useTodayView();
  const rows = list.data?.matters ?? [];
  const id = chosen ?? rows[0]?.id ?? null;
  const detail = useMatter(id);
  if (list.isError) return <ErrorState title={t("matters.error")} onRetry={() => void list.refetch()} />;
  return (
    <div className="grid items-start gap-4 md:grid-cols-matters">
      <aside aria-label={t("matters.list.label")} className="flex flex-col gap-2 rounded-lg border border-line-subtle bg-surface-raised p-2 shadow-raised md:sticky md:top-4">
        <div className="px-2 pt-2"><Segmented label={t("matters.list.label")} hideLabel value={scope} options={[{ value: "open", label: t("matters.list.open") }, { value: "all", label: t("matters.list.all") }]} onChange={setScope} /></div>
        {list.isPending ? <Skeleton className="h-6 w-full" /> : null}
        {list.isSuccess && !rows.length ? <p className="p-3 text-md text-ink-muted">{t("matters.group.empty")}</p> : null}
        <ul data-testid="matter-list" className="flex flex-col">{rows.map((row) => <ListItem key={row.id} matter={row} selected={row.id === id} onPick={() => go("matters", row.id)} />)}</ul>
      </aside>
      <div className="min-w-0">
        {id === null ? <EmptyState icon="tasks" title={t("matters.pick")} /> : null}
        {detail.isPending && id !== null ? <Skeleton className="h-7 w-full" /> : null}
        {detail.isError ? <ErrorState title={t("matters.notFound")} onRetry={() => void detail.refetch()} /> : null}
        {detail.data ? <Detail detail={detail.data} /> : null}
      </div>
    </div>
  );
}
