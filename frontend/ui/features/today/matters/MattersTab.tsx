"use client";

import { useState } from "react";
import type { MatterDetail, MatterRow, MatterWork } from "@/ui/client/contracts.generated";
import { useShortDate, useTimeOnly } from "@/ui/client/format";
import { useMatter, useMatterList, useMatterReopen, useSaveTask, useTasks, useUnlinkThread } from "@/ui/client/work";
import { mailSource } from "@/ui/features/sources/kinds";
import { SourceChip } from "@/ui/features/sources/SourceChip";
import { Icon } from "@/ui/icons";
import { Avatar } from "@/ui/primitives/Avatar";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { RowButton } from "@/ui/primitives/Pressable";
import { Segmented } from "@/ui/primitives/Segmented";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { useToast } from "@/ui/primitives/Toast";
import { MarkGlyph } from "@/ui/primitives/Track";
import { t, tn, type StringKey } from "@/ui/strings";
import { KIND_MARK, StateBadge, StateText, countsOf, kindLabel, useDue, useMatterDoneWithUndo, useTodayView } from "./parts";

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

function Side({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col gap-3 rounded-lg border border-line-subtle bg-surface-raised p-4 shadow-raised">
      <h3 className="text-md font-medium text-ink-primary">{title}</h3>
      {children}
    </section>
  );
}

function Detail({ detail }: { detail: MatterDetail }) {
  const matter = detail.matter;
  const short = useShortDate();
  const time = useTimeOnly();
  const due = useDue();
  const finish = useMatterDoneWithUndo();
  const reopen = useMatterReopen();
  const unlink = useUnlinkThread();
  const toast = useToast();
  const when = matter.due ? due(matter.due) : null;
  const done = matter.state === "done";
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <header data-testid="matter-header" className="flex flex-wrap items-start justify-between gap-4 rounded-lg border border-line-subtle bg-surface-raised p-5 shadow-raised">
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <p className="flex flex-wrap items-center gap-2 text-sm text-ink-muted">
            <StateBadge state={matter.state} />
            {matter.started ? <span className="tabular-nums">{t("matters.started", { when: short(matter.started) })}</span> : null}
            <span>{countsOf(matter)}</span>
          </p>
          <h2 className="font-serif text-title text-ink-primary">{matter.title}</h2>
          {matter.next || when ? (
            <p className="text-lg text-ink-secondary">
              {matter.next ? t("matters.next", { next: matter.next }) : null}
              {when ? <span className={`ml-2 tabular-nums ${when.overdue ? "font-medium text-status-danger" : "text-status-warning"}`}>{when.text}</span> : null}
            </p>
          ) : null}
        </div>
        {done ? <Button onClick={() => reopen.mutate(matter.id)} loading={reopen.isPending}>{t("matters.undo")}</Button> : <Button variant="primary" data-testid="matter-done" onClick={() => finish(matter)}>{t("matters.done")}</Button>}
      </header>
      <div className="today-columns grid items-start gap-4">
        <section aria-label={t("matters.timeline")} className="flex min-w-0 flex-col gap-1 rounded-lg border border-line-subtle bg-surface-raised p-5 shadow-raised">
          <h3 className="text-lg font-medium text-ink-primary">{t("matters.timeline")}</h3>
          <p className="pb-3 text-sm text-ink-muted">{t("matters.timeline.hint")}</p>
          <ol data-testid="matter-timeline" className="flex flex-col">
            <Presence>
              {detail.events.map((event, index) => (
                <Rise as="li" settle key={event.id} className="grid grid-cols-timeline gap-3">
                  <span className="flex flex-col pt-px text-sm tabular-nums text-ink-muted">
                    <span>{short(event.time)}</span>
                    {new Date(event.time).toDateString() === new Date().toDateString() ? null : <span>{time(event.time)}</span>}
                  </span>
                  <span aria-hidden className="flex flex-col items-center">
                    <span className="pt-1"><MarkGlyph {...KIND_MARK[event.kind]} /></span>
                    {index < detail.events.length - 1 ? <span className="w-px flex-1 bg-line-subtle" /> : null}
                  </span>
                  <div className="flex min-w-0 flex-col gap-1 pb-5">
                    <p className="text-md text-ink-primary"><span className="font-medium">{kindLabel(event.kind)}</span><span className="text-ink-secondary"> · {event.text}</span></p>
                    {event.why ? <p className="text-sm text-ink-muted">{t("matters.why", { why: event.why })}</p> : null}
                    {event.source ? <div><SourceChip source={event.source} /></div> : null}
                  </div>
                </Rise>
              ))}
            </Presence>
          </ol>
        </section>
        <div className="flex min-w-0 flex-col gap-4">
          <Side title={t("matters.work")}>
            {matter.work?.length ? <ul className="flex flex-col gap-3">{matter.work.map((item) => <WorkItem key={`${item.kind}-${item.id}`} item={item} />)}</ul> : <p className="text-sm text-ink-muted">{t("matters.work.none")}</p>}
          </Side>
          <Side title={t("matters.together")}>
            <ul className="flex flex-col gap-3">
              {detail.threads.map((thread) => (
                <li key={thread.id} className="flex flex-col gap-1">
                  <SourceChip source={{ ...mailSource(thread.id), title: thread.subject, date: thread.last_date }} />
                  <p className="text-sm text-ink-secondary">{thread.how === "start" ? t("matters.together.start") : thread.why}</p>
                  <span className="flex flex-wrap items-center gap-2 whitespace-nowrap text-sm text-ink-muted">
                    <Badge>{t(`matters.state.${thread.status === "resolved" ? "done" : thread.status === "waiting_on_you" || thread.status === "waiting_on_others" ? thread.status : "fyi"}` as StringKey)}</Badge>
                    {tn("matters.emails", thread.emails)}
                  </span>
                  {detail.threads.length > 1 && thread.how !== "start" ? (
                    <Button variant="quiet" className="-ml-3 self-start py-px" onClick={() => unlink.mutate(thread.id, { onSuccess: () => toast({ title: t("matters.notPart.done") }) })}>{t("matters.notPart")}</Button>
                  ) : null}
                </li>
              ))}
            </ul>
          </Side>
          {detail.people.length ? (
            <Side title={t("matters.people")}>
              <ul className="flex flex-wrap gap-3">
                {detail.people.map((name) => <li key={name} className="flex items-center gap-2 text-md text-ink-secondary"><Avatar name={name} />{name}</li>)}
              </ul>
            </Side>
          ) : null}
        </div>
      </div>
    </div>
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
