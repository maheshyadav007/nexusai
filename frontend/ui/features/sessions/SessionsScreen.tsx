"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useDateTime } from "@/ui/client/format";
import { useCreateSession, useSessions } from "@/ui/client/sessions";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import type { SessionRow } from "@/ui/client/contracts.generated";
import { t, type StringKey } from "@/ui/strings";

export const SESSION_STATES: Readonly<Record<string, { label: StringKey; tone: "running" | "waiting" | "done" | "failed" | "idle" }>> = {
  queued: { label: "sessions.status.queued", tone: "waiting" },
  running: { label: "sessions.status.running", tone: "running" },
  waiting: { label: "sessions.status.waiting", tone: "waiting" },
  done: { label: "sessions.status.done", tone: "done" },
  failed: { label: "sessions.status.failed", tone: "failed" },
  stopped: { label: "sessions.status.stopped", tone: "idle" },
};

function SessionGroup({ title, rows }: { title: string; rows: readonly SessionRow[] }) {
  const format = useDateTime();
  return (
    <section aria-label={title} className="flex flex-col gap-1">
      <h2 className="text-sm text-ink-muted">{title}</h2>
      <ul className="flex flex-col border-t border-line-subtle">
        {rows.map((session) => {
          const state = SESSION_STATES[session.status] ?? { label: "sessions.status.done" as const, tone: "idle" as const };
          const waiting = session.status === "waiting";
          return (
            <li key={session.id} className="border-b border-line-subtle">
              <Link href={`/agent/sessions/${session.id}`} data-testid="session-row" className="focus-ring flex items-center gap-3 px-2 py-2 transition-colors duration-fast hover:bg-surface-raised">
                <StatusDot tone={state.tone} />
                <span className="min-w-0 flex-1 truncate text-md text-ink-primary">{session.title}</span>
                <span className={`shrink-0 text-sm ${waiting ? "font-medium text-accent-default" : "text-ink-muted"}`}>{session.agent === "mail" ? t("sessions.selfRunningLabel") : t(state.label)}</span>
                <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(session.updated)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function SessionsScreen() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const sessions = useSessions(search);
  const create = useCreateSession();
  const rows = sessions.data?.sessions ?? [];
  const waiting = rows.filter((row) => row.status === "waiting");
  const others = rows.filter((row) => row.status !== "waiting");
  return (
    <div className="mx-auto flex max-w-content flex-col gap-4 p-6">
      <header className="flex items-center justify-between gap-3">
        <h1 className="font-serif text-display text-ink-primary">{t("nav.sessions")}</h1>
        <Button variant="primary" loading={create.isPending} onClick={() => create.mutate({}, { onSuccess: (session) => router.push(`/agent/sessions/${session.id}`) })}>
          {t("sessions.new")}
        </Button>
      </header>
      {sessions.data ? <p className="text-sm tabular-nums text-ink-muted">{t("sessions.running", { running: sessions.data.running, limit: sessions.data.limit })}</p> : null}
      <Field label={t("sessions.search")}>{({ invalid, ...control }) => <Input invalid={invalid} value={search} onChange={(event) => setSearch(event.target.value)} {...control} />}</Field>
      {sessions.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {sessions.isError ? <ErrorState title={t("sessions.error")} onRetry={() => void sessions.refetch()} /> : null}
      {sessions.isSuccess && rows.length === 0 ? <EmptyState icon="sessions" title={t("sessions.empty.title")} description={t("sessions.empty.description")} /> : null}
      {waiting.length ? <SessionGroup title={t("sessions.waitingOnYou")} rows={waiting} /> : null}
      {others.length ? <SessionGroup title={waiting.length ? t("sessions.others") : t("nav.sessions")} rows={others} /> : null}
    </div>
  );
}
