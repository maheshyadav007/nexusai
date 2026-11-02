"use client";

import type { Pipeline } from "@/ui/client/contracts.generated";
import { useDateTime } from "@/ui/client/format";
import { useState } from "react";
import { usePausePipeline, usePipelineMore, usePipelines, useRunPipeline, useStopPipeline } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { t } from "@/ui/strings";

const TONES = { running: "running", waiting: "done", stopped: "idle", problem: "failed" } as const;

const SUGGESTED_MORE = "1000";

function GetMore({ row }: { row: Pipeline }) {
  const more = usePipelineMore();
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState(SUGGESTED_MORE);
  const left = row.left ?? 0;
  const close = { onSuccess: () => setOpen(false) };
  return (
    <Dialog title={t("pipelines.more.title")} description={t("pipelines.more.description", { left: left.toLocaleString() })} open={open} onOpenChange={setOpen} trigger={<Button variant="quiet" className="py-px">{t("pipelines.more")}</Button>}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          more.mutate({ id: row.id, count: Number(count) }, close);
        }}
      >
        <Field label={t("pipelines.more.count")} hint={t("pipelines.more.hint")}>{({ invalid, ...control }) => <Input type="number" min={1} invalid={invalid} value={count} onChange={(event) => setCount(event.target.value)} {...control} />}</Field>
        <div className="flex flex-wrap justify-end gap-2">
          <Button loading={more.isPending} onClick={() => more.mutate({ id: row.id, count: null }, close)}>{t("pipelines.more.all", { left: left.toLocaleString() })}</Button>
          <Button type="submit" variant="primary" loading={more.isPending} disabled={!(Number(count) >= 1)}>{t("pipelines.more.get")}</Button>
        </div>
      </form>
    </Dialog>
  );
}

export function PipelineRow({ row }: { row: Pipeline }) {
  const pause = usePausePipeline();
  const stop = useStopPipeline();
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
            {row.history_open && !stopped ? <Button variant="quiet" className="py-px" loading={stop.isPending} onClick={() => stop.mutate(row.id)}>{t("pipelines.stop")}</Button> : null}
            {row.history_open || !row.left ? null : <GetMore row={row} />}
            <Button variant="quiet" className="py-px" loading={pause.isPending} onClick={() => pause.mutate({ id: row.id, paused: !stopped })}>{t(stopped ? "pipelines.resume" : "pipelines.pause")}</Button>
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
