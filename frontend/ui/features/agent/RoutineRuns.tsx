"use client";

import { useDateTime } from "@/ui/client/format";
import { useRoutineRuns, useRunAgain } from "@/ui/client/work";
import { SessionLink } from "@/ui/features/assistant/SessionLink";
import { Button } from "@/ui/primitives/Button";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { t, type StringKey } from "@/ui/strings";

const TONE: Readonly<Record<string, "done" | "failed" | "running" | "idle">> = { done: "done", failed: "failed", running: "running", pending: "running", skipped: "idle" };

/** A routine's latest runs: when, how each ended, its chat, and Run again for one that failed. */
export function RoutineRuns({ schedule, trigger }: { schedule?: number; trigger?: string }) {
  const runs = useRoutineRuns(schedule !== undefined ? { schedule } : { trigger: trigger ?? "" });
  const again = useRunAgain();
  const format = useDateTime();
  const rows = runs.data?.runs ?? [];
  return (
    <section className="flex flex-col gap-2">
      <h4 className="text-sm font-medium text-ink-muted">{t("routines.runs")}</h4>
      {rows.length ? (
        <ul data-testid="routine-runs" className="flex flex-col">
          {rows.map((run) => (
            <li key={run.id} className="flex flex-wrap items-center gap-3 border-t border-line-subtle py-2 text-md">
              <StatusDot tone={TONE[run.status] ?? "idle"} />
              <span className="tabular-nums text-ink-muted">{format(run.time)}</span>
              <span className="min-w-0 flex-1 text-ink-secondary">
                {t(`routines.run.${run.status}` as StringKey)}
                {run.error ? ` · ${run.error}` : ""}
              </span>
              {run.session ? <SessionLink className="text-sm" session={run.session}>{t("routines.run.open")}</SessionLink> : null}
              {run.status === "failed" ? <Button variant="quiet" loading={again.isPending} onClick={() => again.mutate(run.id)}>{t("routines.run.again")}</Button> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-md text-ink-muted">{t("routines.runs.none")}</p>
      )}
    </section>
  );
}
