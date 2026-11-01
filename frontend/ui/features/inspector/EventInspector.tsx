"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { eventLog } from "@/ui/client/api";
import type { AppEvent } from "@/ui/client/contracts.generated";
import { useEvents } from "@/ui/client/events";
import { Card } from "@/ui/primitives/Card";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { t } from "@/ui/strings";

export function EventInspector() {
  const { connected, subscribe } = useEvents();
  const { data } = useQuery({ queryKey: ["event-log"], queryFn: () => eventLog({ since: 0 }) });
  const [live, setLive] = useState<AppEvent[]>([]);

  useEffect(() => subscribe((event) => setLive((current) => [...current, event])), [subscribe]);

  const bySeq = new Map([...(data?.events ?? []), ...live].map((event) => [event.seq, event]));
  const events = [...bySeq.values()].sort((a, b) => b.seq - a.seq);
  const failed = data?.failed ?? [];
  const columns = ["seq", "type", "source", "trace", "payload"] as const;

  return (
    <Card
      title={t("inspector.title")}
      description={t("inspector.description")}
      aside={
        <span className="flex items-center gap-2 text-sm text-ink-muted">
          <StatusDot tone={connected ? "done" : "failed"} />
          {connected ? t("inspector.live") : t("inspector.offline")}
        </span>
      }
    >
      {events.length === 0 ? (
        <p className="text-sm text-ink-muted">{t("inspector.empty")}</p>
      ) : (
        <table className="w-full table-fixed border-collapse text-left text-sm">
          <thead className="text-xs text-ink-muted">
            <tr>
              {columns.map((column) => (
                <th key={column} className="border-b border-line-subtle pb-2 pr-3 font-medium">
                  {t(`inspector.column.${column}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono text-xs text-ink-secondary">
            {events.map((event) => (
              <tr key={event.id} data-testid="event-row">
                <td className="border-b border-line-subtle py-2 pr-3">{event.seq}</td>
                <td className="border-b border-line-subtle py-2 pr-3 text-ink-primary">{event.type}</td>
                <td className="border-b border-line-subtle py-2 pr-3">{event.source}</td>
                <td className="truncate border-b border-line-subtle py-2 pr-3" title={event.trace_id}>{event.trace_id}</td>
                <td className="truncate border-b border-line-subtle py-2 pr-3" title={JSON.stringify(event.payload)}>{JSON.stringify(event.payload)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {failed.length > 0 ? (
        <div className="mt-4">
          <h3 className="mb-2 text-sm font-medium text-status-danger">{t("inspector.failed")}</h3>
          <ul className="font-mono text-xs text-ink-secondary">
            {failed.map((item) => (
              <li key={`${item.listener}-${item.event_seq}`}>{item.listener} · {item.event_type} · {item.error}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}
