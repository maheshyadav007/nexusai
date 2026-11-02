"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { GetCockpitEvents, Job } from "@/ui/client/contracts.generated";
import { usePausePst, useStopFindPst } from "@/ui/client/documents";
import { useEvents } from "@/ui/client/events";
import { useDateTime } from "@/ui/client/format";
import { useCancelModel } from "@/ui/client/semantic";
import { useStopSession } from "@/ui/client/sessions";
import { useCockpit, useCockpitEvents, useTriageEstimate, useTriageExisting } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
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
// A busy moment can bring many events a second, and reading the list once covers them all.
const REFRESH_MS = 1000;

function JobRow({ job }: { job: Job }) {
  const stop = useStopSession();
  const pausePst = usePausePst();
  const stopLooking = useStopFindPst();
  const cancelModel = useCancelModel();
  const session = job.id.startsWith(SESSION_PREFIX) ? job.id.slice(SESSION_PREFIX.length) : null;
  const importing = job.kind === "pst" && job.status !== "paused" ? Number(job.id.slice(PST_PREFIX.length)) : null;
  const model = job.kind === "model" ? job.id.slice(MODEL_PREFIX.length) : null;
  return (
    <li data-testid="job" className="flex flex-col gap-2 rounded-md border border-line-subtle p-3">
      <div className="flex items-center justify-between gap-3 text-md">
        <Link href={job.link ?? "/cockpit"} className="focus-ring min-w-0 truncate rounded-sm text-ink-primary underline-offset-2 hover:underline">
          {job.title}
        </Link>
        <span className="flex shrink-0 items-center gap-2 text-sm text-ink-secondary">
          {job.status}
          {session ? <Button variant="quiet" className="py-px" loading={stop.isPending} onClick={() => stop.mutate(session)}>{t("sessions.stop")}</Button> : null}
          {importing !== null ? <Button variant="quiet" className="py-px" onClick={() => pausePst.mutate(importing)}>{t("pst.pause")}</Button> : null}
          {job.kind === "pst-search" ? <Button variant="quiet" className="py-px" onClick={() => stopLooking.mutate(undefined)}>{t("pst.find.stop")}</Button> : null}
          {model ? <Button variant="quiet" className="py-px" onClick={() => cancelModel.mutate(model)}>{t("semantic.cancel")}</Button> : null}
        </span>
      </div>
      {job.progress != null && job.total ? <Progress label={job.title} value={job.progress} max={job.total} /> : null}
      {job.progress != null && job.total ? <p className="text-sm tabular-nums text-ink-muted">{t("cockpit.progress", { done: job.progress, total: job.total })}</p> : null}
    </li>
  );
}

function RunningNow() {
  const cockpit = useCockpit();
  const format = useDateTime();
  const estimate = useTriageEstimate();
  const triage = useTriageExisting();
  const jobs = cockpit.data?.jobs ?? [];
  const upcoming = cockpit.data?.upcoming ?? [];
  const untriaged = estimate.data?.untriaged ?? 0;
  return (
    <section aria-label={t("cockpit.running")} className="flex flex-col gap-3">
      <h2 className="text-lg font-medium text-ink-primary">{t("cockpit.running")}</h2>
      {cockpit.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {cockpit.isError ? <ErrorState title={t("cockpit.error")} onRetry={() => void cockpit.refetch()} /> : null}
      {cockpit.isSuccess && !jobs.length ? <EmptyState icon="cockpit" title={t("activity.idle")} /> : null}
      <ul className="flex flex-col gap-2">
        {jobs.map((job) => (
          <JobRow key={job.id} job={job} />
        ))}
      </ul>
      {upcoming.length ? (
        <>
          <h3 className="text-md font-medium text-ink-primary">{t("cockpit.upcoming")}</h3>
          <ul data-testid="upcoming" className="flex flex-col border-t border-line-subtle">
            {upcoming.map((run) => (
              <li key={run.id} className="flex items-baseline justify-between gap-3 border-b border-line-subtle py-2 text-md">
                <span className="min-w-0 truncate text-ink-primary">{run.title}</span>
                <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(run.when)}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {untriaged > 0 ? (
        <Card title={t("background.older")} description={tn("background.older.description", untriaged, { tokens: (estimate.data?.approx_tokens ?? 0).toLocaleString() })}>
          <Button loading={triage.isPending} onClick={() => triage.mutate(true)}>{t("background.older.action")}</Button>
        </Card>
      ) : null}
    </section>
  );
}

function Health() {
  const cockpit = useCockpit();
  const format = useDateTime();
  const items = cockpit.data?.health ?? [];
  return (
    <section aria-label={t("cockpit.health")} className="flex flex-col gap-3">
      <h2 className="text-lg font-medium text-ink-primary">{t("cockpit.health")}</h2>
      <ul data-testid="health" className="grid gap-px md:grid-cols-2">
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
  const format = useDateTime();
  const rows = feed.data?.events ?? [];
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
        <Segmented label={t("cockpit.filter")} hideLabel value={filter} options={options} onChange={setFilter} />
      </div>
      {feed.isError ? <ErrorState title={t("cockpit.error")} onRetry={() => void feed.refetch()} /> : null}
      {feed.isSuccess && !rows.length ? <EmptyState icon="activity" title={t("cockpit.events.none")} /> : null}
      <ul className="flex flex-col border-t border-line-subtle">
        {rows.map((row) => (
          <li key={row.seq} data-testid="cockpit-event" className="flex items-start justify-between gap-3 border-b border-line-subtle py-2">
            <span className="flex min-w-0 items-start gap-2">
              {row.problem ? <span className="pt-1"><StatusDot tone="failed" /></span> : null}
              <span className="flex min-w-0 flex-col">
                {row.link ? (
                  <Link href={row.link} className="focus-ring break-words rounded-sm text-md text-ink-primary underline-offset-2 hover:underline">{row.title}</Link>
                ) : (
                  <span className="break-words text-md text-ink-primary">{row.title}</span>
                )}
                {row.detail ? <span className="break-words text-sm text-ink-muted">{row.detail}</span> : null}
              </span>
            </span>
            <time dateTime={row.time} className="shrink-0 text-sm tabular-nums text-ink-muted">{format(row.time)}</time>
          </li>
        ))}
      </ul>
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
    <div className="mx-auto flex max-w-reading flex-col gap-6 p-6">
      <PageHeader title={t("nav.cockpit")} summary={t("cockpit.description")} />
      <Health />
      <RunningNow />
      <Feed />
    </div>
  );
}
