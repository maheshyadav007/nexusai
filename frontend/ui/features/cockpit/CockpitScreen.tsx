"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { GetCockpitEvents, Job } from "@/ui/client/contracts.generated";
import { usePausePst, useStopFindPst } from "@/ui/client/documents";
import { useEvents } from "@/ui/client/events";
import { useRelativeTime, useDateTime } from "@/ui/client/format";
import { useCancelModel } from "@/ui/client/semantic";
import { useStopSession } from "@/ui/client/sessions";
import { useCockpit, useCockpitEvents, useStopPipeline, useTriageEstimate, useTriageExisting } from "@/ui/client/work";
import { Pipelines } from "@/ui/features/cockpit/Pipelines";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { PageHeader } from "@/ui/primitives/PageHeader";
import { Progress } from "@/ui/primitives/Progress";
import { Segmented } from "@/ui/primitives/Segmented";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { TextLink } from "@/ui/primitives/TextLink";
import { t, tn } from "@/ui/strings";

type Filter = NonNullable<GetCockpitEvents["filter"]>;

const HEALTH_TONES = { ok: "done", working: "running", problem: "failed", off: "idle" } as const;
const SESSION_PREFIX = "session-";
const PST_PREFIX = "pst-";
const MODEL_PREFIX = "model-";
const MAIL_PIPELINE = "mail-sync";
// A busy moment can bring many events a second, and reading the list once covers them all.
const REFRESH_MS = 1000;
const FEED_PREVIEW = 8;

function JobRow({ job }: { job: Job }) {
  const stop = useStopSession();
  const pausePst = usePausePst();
  const stopLooking = useStopFindPst();
  const cancelModel = useCancelModel();
  const stopSync = useStopPipeline();
  const session = job.id.startsWith(SESSION_PREFIX) ? job.id.slice(SESSION_PREFIX.length) : null;
  const importing = job.kind === "pst" && job.status !== "paused" ? Number(job.id.slice(PST_PREFIX.length)) : null;
  const model = job.kind === "model" ? job.id.slice(MODEL_PREFIX.length) : null;
  return (
    <Rise as="li" settle="position" data-testid="job" className="flex flex-col gap-2 border-b border-line-subtle py-3">
      <div className="flex items-center justify-between gap-3 text-md">
        <Link href={job.link ?? "/cockpit"} className="focus-ring min-w-0 truncate rounded-sm text-ink-primary underline-offset-2 hover:underline">
          {job.title}
        </Link>
        <span className="flex shrink-0 items-center gap-2 text-sm text-ink-secondary">
          {job.status}
          {session ? <Button variant="quiet" className="py-px" loading={stop.isPending} onClick={() => stop.mutate(session)}>{t("sessions.stop")}</Button> : null}
          {job.kind === "sync" ? <Button variant="quiet" className="py-px" loading={stopSync.isPending} onClick={() => stopSync.mutate(MAIL_PIPELINE)}>{t("pipelines.stop")}</Button> : null}
          {importing !== null ? <Button variant="quiet" className="py-px" onClick={() => pausePst.mutate(importing)}>{t("pst.pause")}</Button> : null}
          {job.kind === "pst-search" ? <Button variant="quiet" className="py-px" onClick={() => stopLooking.mutate(undefined)}>{t("pst.find.stop")}</Button> : null}
          {model ? <Button variant="quiet" className="py-px" onClick={() => cancelModel.mutate(model)}>{t("semantic.cancel")}</Button> : null}
        </span>
      </div>
      {job.progress != null && job.total ? <Progress label={job.title} value={job.progress} max={job.total} /> : null}
      {job.progress != null && job.total ? <p className="text-sm tabular-nums text-ink-muted">{t("cockpit.progress", { done: job.progress, total: job.total })}</p> : null}
    </Rise>
  );
}

function RunningNow() {
  const cockpit = useCockpit();
  // Mail sync has its own controls under Background; do not list it twice.
  const jobs = (cockpit.data?.jobs ?? []).filter((job) => job.kind !== "sync");
  return (
    <section aria-label={t("cockpit.running")} className="flex flex-col gap-3">
      <h2 className="text-lg font-medium text-ink-primary">{t("cockpit.running")}</h2>
      {cockpit.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {cockpit.isError ? <ErrorState title={t("cockpit.error")} onRetry={() => void cockpit.refetch()} /> : null}
      {cockpit.isSuccess && !jobs.length ? <p className="py-3 text-md text-ink-muted">{t("cockpit.quiet")}</p> : null}
      <ul className="flex flex-col"><Presence>{jobs.map((job) => <JobRow key={job.id} job={job} />)}</Presence></ul>
    </section>
  );
}

function Upcoming() {
  const cockpit = useCockpit();
  const format = useDateTime();
  const upcoming = cockpit.data?.upcoming ?? [];
  return <section aria-label={t("cockpit.upcoming")} className="flex flex-col gap-3">
    <div className="flex items-baseline justify-between gap-3"><h2 className="text-lg font-medium text-ink-primary">{t("cockpit.upcoming")}</h2><TextLink className="text-sm" href="/agent/schedules">{t("cockpit.upcoming.all")}</TextLink></div>
    {!upcoming.length ? <p className="text-sm text-ink-muted">{t("cockpit.noUpcoming")}</p> : null}
    <ul data-testid="upcoming" className="flex flex-col"><Presence>{upcoming.map((run) => <Rise as="li" settle="position" key={run.id} className="flex flex-col gap-1 border-b border-line-subtle py-3"><span className="text-md text-ink-primary">{run.title}</span><span className="text-sm tabular-nums text-ink-muted">{format(run.when)}</span></Rise>)}</Presence></ul>
  </section>;
}

function Maintenance() {
  const estimate = useTriageEstimate();
  const triage = useTriageExisting();
  const untriaged = estimate.data?.untriaged ?? 0;
  return <ExpandRow variant="plain" label={t("cockpit.maintenance")} title={t("cockpit.maintenance")} meta={t("cockpit.maintenance.hint")}>
    <Pipelines />
    {untriaged > 0 ? <Card title={t("background.older")} description={tn("background.older.description", untriaged, { tokens: (estimate.data?.approx_tokens ?? 0).toLocaleString() })}><Button loading={triage.isPending} onClick={() => triage.mutate(true)}>{t("background.older.action")}</Button></Card> : null}
  </ExpandRow>;
}

function Health() {
  const cockpit = useCockpit();
  const format = useDateTime();
  const items = cockpit.data?.health ?? [];
  return (
    <section aria-label={t("cockpit.health")} className="flex flex-col gap-3">
      <h2 className="text-lg font-medium text-ink-primary">{t("cockpit.health")}</h2>
      <ul data-testid="health" className="flex flex-col">
        {items.map((item) => (
          <li key={item.id} data-testid={`health-${item.id}`}>
            <Link href={item.link ?? "/cockpit"} className="focus-ring flex items-start gap-2 rounded-md p-2 transition-colors duration-fast hover:bg-surface-sunken">
              <span className="pt-1"><StatusDot tone={HEALTH_TONES[item.state]} /></span>
              <span className="flex min-w-0 flex-col">
                <span className="text-md text-ink-primary">{item.label}</span>
                <span className="truncate text-sm tabular-nums text-ink-muted">{item.when ? format(item.when) : item.detail}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Feed() {
  const [filter, setFilter] = useState<Filter>("all");
  const feed = useCockpitEvents(filter);
  const [expanded, setExpanded] = useState(false);
  const relative = useRelativeTime();
  const format = useDateTime();
  const all: ((NonNullable<typeof feed.data>["events"])[number] & { repeats: number })[] = [];
  for (const event of feed.data?.events ?? []) {
    const previous = all[all.length - 1];
    if (previous && previous.title === event.title && previous.detail === event.detail && previous.link === event.link && previous.problem === event.problem) previous.repeats += 1;
    else all.push({ ...event, repeats: 1 });
  }
  const rows = expanded ? all : all.slice(0, FEED_PREVIEW);
  const options: readonly { value: Filter; label: string }[] = [
    { value: "all", label: t("cockpit.filter.all") },
    { value: "agents", label: t("cockpit.filter.agents") },
    { value: "mail", label: t("cockpit.filter.mail") },
    { value: "indexing", label: t("cockpit.filter.indexing") },
    { value: "problems", label: t("cockpit.filter.problems") },
  ];
  return (
    <section aria-label={t("cockpit.events")} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-medium text-ink-primary">{t("cockpit.events")}</h2>
        <Segmented label={t("cockpit.filter")} hideLabel value={filter} options={options} onChange={(next) => { setFilter(next); setExpanded(false); }} />
      </div>
      {feed.isError ? <ErrorState title={t("cockpit.error")} onRetry={() => void feed.refetch()} /> : null}
      {feed.isSuccess && !rows.length ? <EmptyState icon="activity" title={t("cockpit.events.none")} /> : null}
      <ul className="flex flex-col border-t border-line-subtle">
        <Presence>
        {rows.map((row) => (
          <Rise as="li" settle="position" key={row.seq} data-testid="cockpit-event" className="flex items-start justify-between gap-3 border-b border-line-subtle py-2">
            <span className="flex min-w-0 items-start gap-2">
              {row.problem ? <span className="pt-1"><StatusDot tone="failed" /></span> : null}
              <span className="flex min-w-0 flex-col">
                {row.link ? (
                  <Link href={row.link} className="focus-ring break-words rounded-sm text-md text-ink-primary underline-offset-2 hover:underline">{row.title}</Link>
                ) : (
                  <span className="break-words text-md text-ink-primary">{row.title}</span>
                )}
                {row.repeats > 1 ? <span className="text-sm tabular-nums text-ink-muted">{t("cockpit.repeats", { count: row.repeats })}</span> : null}
                {row.detail ? <span className="break-words text-sm text-ink-muted">{row.detail}</span> : null}
              </span>
            </span>
            <time dateTime={row.time} title={format(row.time)} className="shrink-0 text-sm tabular-nums text-ink-muted">{relative(row.time)}</time>
          </Rise>
        ))}
        </Presence>
      </ul>
      {all.length > FEED_PREVIEW ? <div><Button variant="quiet" onClick={() => setExpanded((value) => !value)}>{t(expanded ? "cockpit.less" : "cockpit.more")}</Button></div> : null}
      <p className="text-sm">
        <TextLink href="/logs">{t("cockpit.events.everything")}</TextLink>
      </p>
    </section>
  );
}

/** One place to see everything that's running and everything worth knowing that just happened. */
export function CockpitScreen() {
  const client = useQueryClient();
  const { subscribe } = useEvents();
  const cockpit = useCockpit();
  const health = cockpit.data?.health ?? [];
  const problems = health.filter((item) => item.state === "problem");
  const running = (cockpit.data?.jobs ?? []).filter((job) => job.kind !== "sync").length;
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const stop = subscribe(() => {
      timer ??= setTimeout(() => {
        timer = null;
        void client.invalidateQueries({ queryKey: ["cockpit"] });
        void client.invalidateQueries({ queryKey: ["cockpit-events"] });
      }, REFRESH_MS);
    });
    return () => {
      stop();
      if (timer) clearTimeout(timer);
    };
  }, [client, subscribe]);
  return (
    <div className="cockpit-container mx-auto flex max-w-page flex-col gap-5 p-6">
      <PageHeader title={t("nav.cockpit")} summary={t("cockpit.overview")} />
      {cockpit.data ? <div data-testid="cockpit-overview" className="flex flex-wrap items-center gap-5 border-y border-line-subtle py-4">
        <span className="flex items-center gap-2 text-md text-ink-primary"><StatusDot tone={problems.length ? "failed" : "done"} />{problems.length ? tn("cockpit.attentionCount", problems.length) : t("cockpit.healthy")}</span>
        <span className="text-sm tabular-nums text-ink-muted">{t("cockpit.runningCount", { count: running })}</span>
        <span className="text-sm tabular-nums text-ink-muted">{t("cockpit.upcomingCount", { count: cockpit.data.upcoming.length })}</span>
      </div> : null}
      {problems.length ? <Rise className="flex flex-col gap-2 border-l border-status-warning pl-4"><h2 className="text-md font-medium text-ink-primary">{t("cockpit.attention")}</h2>{problems.map((item) => <TextLink key={item.id} href={item.link ?? "/logs"}>{item.label}: {item.detail}</TextLink>)}</Rise> : null}
      <div className="cockpit-columns grid items-start gap-6">
        <div className="flex min-w-0 flex-col gap-6">
          <Rise className="flex flex-col gap-4"><RunningNow /><Maintenance /></Rise>
          <Rise><Feed /></Rise>
        </div>
        <aside className="cockpit-aside flex min-w-0 flex-col gap-6 border-t border-line-subtle pt-4">
          <Rise><Upcoming /></Rise>
          <ExpandRow variant="plain" label={t("cockpit.health")} title={t("cockpit.health")} meta={t("cockpit.health.hint")} defaultOpen={problems.length > 0}><Health /></ExpandRow>
        </aside>
      </div>
    </div>
  );
}
