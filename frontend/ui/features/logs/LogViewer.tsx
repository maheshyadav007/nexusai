"use client";

import { useEffect, useState } from "react";
import { useDateTime } from "@/ui/client/format";
import { useLogs, useTrace } from "@/ui/client/system";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { t } from "@/ui/strings";

type Line = Record<string, unknown>;

const LEVELS = [
  { value: "all", label: t("logs.level.all") },
  { value: "info", label: t("logs.level.info") },
  { value: "warning", label: t("logs.level.warning") },
  { value: "error", label: t("logs.level.error") },
];
const TONES: Readonly<Record<string, string>> = { error: "text-status-danger", warning: "text-status-warning" };
const SHOWN_ELSEWHERE = new Set(["timestamp", "level", "event", "trace_id"]);
const LIVE_LIMIT = 500;

const details = (line: Line) =>
  Object.entries(line)
    .filter(([key]) => !SHOWN_ELSEWHERE.has(key))
    .map(([key, value]) => `${key}=${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(" ");

function matches(line: Line, level: string, text: string) {
  if (level !== "all" && line.level !== level) return false;
  return !text || JSON.stringify(line).toLowerCase().includes(text.toLowerCase());
}

function TraceDialog({ traceId, onClose }: { traceId: string | null; onClose: () => void }) {
  const trace = useTrace(traceId);
  return (
    <Dialog title={t("logs.trace.title")} {...(traceId ? { description: traceId } : {})} shape="drawer" open={Boolean(traceId)} onOpenChange={(open) => (open ? null : onClose())}>
      {trace.isPending ? <Skeleton /> : null}
      {trace.isError ? <ErrorState title={t("logs.trace.error")} /> : null}
      {trace.data ? (
        <div className="flex flex-col gap-4 overflow-y-auto">
          <section>
            <h3 className="mb-2 text-md font-medium">{t("logs.trace.events")}</h3>
            <ul data-testid="trace-events" className="flex flex-col gap-1 font-mono text-sm text-ink-secondary">
              {trace.data.events.map((event) => (
                <li key={String(event.seq)} className="break-all">
                  {String(event.seq)} {String(event.type)} {JSON.stringify(event.payload)}
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h3 className="mb-2 text-md font-medium">{t("logs.trace.lines")}</h3>
            <ul className="flex flex-col gap-1 font-mono text-sm text-ink-secondary">
              {trace.data.lines.map((line, index) => (
                <li key={index} className="break-all">
                  {String(line.level)} {String(line.event)} {details(line)}
                </li>
              ))}
            </ul>
          </section>
        </div>
      ) : null}
    </Dialog>
  );
}

export function LogViewer() {
  const [level, setLevel] = useState("all");
  const [text, setText] = useState("");
  const [traceId, setTraceId] = useState<string | null>(null);
  const [live, setLive] = useState<Line[]>([]);
  const [connected, setConnected] = useState(false);
  const logs = useLogs({ ...(level === "all" ? {} : { level }), ...(text ? { text } : {}) });
  const format = useDateTime();

  useEffect(() => {
    const source = new EventSource("/api/logs/stream");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (message) => setLive((current) => [JSON.parse(message.data as string) as Line, ...current].slice(0, LIVE_LIMIT));
    return () => source.close();
  }, []);

  const lines = [...live.filter((line) => matches(line, level, text)), ...(logs.data?.lines ?? [])];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <Field label={t("logs.search")}>{({ invalid, ...control }) => <Input invalid={invalid} value={text} onChange={(event) => setText(event.target.value)} {...control} />}</Field>
        </div>
        <div className="w-popover max-w-full">
          <Field label={t("logs.level")}>{({ invalid, id }) => <Select id={id} invalid={invalid} value={level} options={LEVELS} onChange={setLevel} />}</Field>
        </div>
        <p role="status" className="flex items-center gap-2 py-2 text-sm text-ink-muted">
          <StatusDot tone={connected ? "done" : "failed"} />
          {t(connected ? "inspector.live" : "inspector.offline")}
        </p>
      </div>
      {logs.isPending ? <Skeleton /> : null}
      {logs.isError ? <ErrorState title={t("logs.error")} onRetry={() => void logs.refetch()} /> : null}
      {logs.isSuccess && lines.length === 0 ? <EmptyState icon="logs" title={t("logs.empty")} /> : null}
      {lines.length > 0 ? (
        <table className="w-full table-fixed border-collapse text-left text-sm">
          <thead className="text-sm text-ink-muted">
            <tr>
              <th className="w-1/6 border-b border-line-subtle pb-2 pr-3 font-medium">{t("logs.column.time")}</th>
              <th className="w-1/12 border-b border-line-subtle pb-2 pr-3 font-medium">{t("logs.column.level")}</th>
              <th className="w-1/6 border-b border-line-subtle pb-2 pr-3 font-medium">{t("logs.column.event")}</th>
              <th className="border-b border-line-subtle pb-2 pr-3 font-medium">{t("logs.column.details")}</th>
              <th className="w-1/12 border-b border-line-subtle pb-2 font-medium">{t("logs.column.trace")}</th>
            </tr>
          </thead>
          <tbody className="text-ink-secondary">
            {lines.slice(0, LIVE_LIMIT).map((line, index) => (
              <tr key={index} data-testid="log-row" className="align-top">
                <td className="border-b border-line-subtle py-1 pr-3 tabular-nums">{format(String(line.timestamp ?? ""))}</td>
                <td className={`border-b border-line-subtle py-1 pr-3 ${TONES[String(line.level)] ?? ""}`}>{String(line.level ?? "")}</td>
                <td className="break-words border-b border-line-subtle py-1 pr-3 font-mono">{String(line.event ?? "")}</td>
                <td className="break-words border-b border-line-subtle py-1 pr-3 font-mono">{details(line)}</td>
                <td className="border-b border-line-subtle py-1">
                  {line.trace_id ? (
                    <Button variant="quiet" className="px-1 py-px" onClick={() => setTraceId(String(line.trace_id))}>
                      {t("logs.trace.open")}
                    </Button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <TraceDialog traceId={traceId} onClose={() => setTraceId(null)} />
    </div>
  );
}
