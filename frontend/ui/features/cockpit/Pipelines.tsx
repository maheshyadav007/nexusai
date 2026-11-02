"use client";

import type { Pipeline } from "@/ui/client/contracts.generated";
import { useDateTime } from "@/ui/client/format";
import { usePausePipeline, usePipelines, useRunPipeline } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { t } from "@/ui/strings";

const TONES = { running: "running", waiting: "done", stopped: "idle", problem: "failed" } as const;

function PipelineRow({ row }: { row: Pipeline }) {
  const pause = usePausePipeline();
  const run = useRunPipeline();
  const format = useDateTime();
  const stopped = row.state === "stopped";
  return (
    <li data-testid="pipeline" className="flex flex-col gap-2 rounded-md border border-line-subtle p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-2 text-md text-ink-primary">
          <StatusDot tone={TONES[row.state]} />
          {row.title}
        </span>
        {row.available ? (
          <span className="flex shrink-0 items-center gap-2">
            {stopped ? null : <Button variant="quiet" className="py-px" loading={run.isPending} onClick={() => run.mutate(row.id)}>{t("pipelines.run")}</Button>}
            <Button variant="quiet" className="py-px" loading={pause.isPending} onClick={() => pause.mutate({ id: row.id, paused: !stopped })}>{t(stopped ? "pipelines.resume" : "pipelines.stop")}</Button>
          </span>
        ) : null}
      </div>
      <p className="text-sm text-ink-secondary">{row.cadence}</p>
      {row.message ? <p role="status" className="text-sm text-ink-secondary">{row.message}</p> : null}
      {row.facts?.length ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm md:grid-cols-4">
          {row.facts.map((fact) => (
            <div key={fact.label} className="flex flex-col">
              <dt className="text-ink-muted">{fact.label}</dt>
              <dd className="tabular-nums text-ink-primary">{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {row.last_run ? (
        <p className="text-sm tabular-nums text-ink-muted">
          {t("pipelines.lastRun", { when: format(row.last_run) })}
          {row.next_run && !stopped ? ` · ${t("pipelines.nextRun", { when: format(row.next_run) })}` : ""}
        </p>
      ) : null}
    </li>
  );
}

/** Work on a timer with no agent involved. It reads the same on the Schedules page and the Cockpit. */
export function Pipelines() {
  const pipelines = usePipelines();
  return (
    <section aria-label={t("pipelines.title")} className="flex flex-col gap-3">
      <div>
        <h2 className="text-lg font-medium text-ink-primary">{t("pipelines.title")}</h2>
        <p className="text-sm text-ink-secondary">{t("pipelines.description")}</p>
      </div>
      {pipelines.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {pipelines.isError ? <ErrorState title={t("pipelines.error")} onRetry={() => void pipelines.refetch()} /> : null}
      <ul className="flex flex-col gap-2">
        {pipelines.data?.pipelines.map((row) => <PipelineRow key={row.id} row={row} />)}
      </ul>
    </section>
  );
}
