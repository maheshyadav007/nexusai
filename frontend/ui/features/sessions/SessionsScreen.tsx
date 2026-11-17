"use client";

import { useState } from "react";
import type { SessionRow } from "@/ui/client/contracts.generated";
import { useShortDate, useTimeOnly } from "@/ui/client/format";
import { isManagedSession, useArchiveSession, useSessions } from "@/ui/client/sessions";
import { useAgentCards } from "@/ui/client/work";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Input } from "@/ui/primitives/Input";
import { ListGroup, ListRow } from "@/ui/primitives/List";
import { LiveDot } from "@/ui/primitives/LiveDot";
import { Mascot } from "@/ui/primitives/Mascot";
import { PageHeader } from "@/ui/primitives/PageHeader";
import { Segmented } from "@/ui/primitives/Segmented";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t, tn, type StringKey } from "@/ui/strings";
import { groupSessions } from "./sessionGroups";

export const SESSION_STATES: Readonly<Record<string, { label: StringKey; tone: "running" | "waiting" | "done" | "failed" | "idle" }>> = {
  queued: { label: "sessions.status.queued", tone: "waiting" },
  running: { label: "sessions.status.running", tone: "running" },
  waiting: { label: "sessions.status.waiting", tone: "waiting" },
  done: { label: "sessions.status.done", tone: "done" },
  failed: { label: "sessions.status.failed", tone: "failed" },
  stopped: { label: "sessions.status.stopped", tone: "idle" },
};

type Filter = "all" | "waiting" | "agents";

function Lead({ row }: { row: SessionRow }) {
  const card = (useAgentCards().data?.cards ?? []).find((item) => item.id === row.agent);
  return (
    <span className="flex h-6 w-6 items-center justify-center rounded-md bg-surface-sunken">
      {row.status === "waiting" ? <LiveDot tone="waiting" /> : row.status === "running" || row.status === "queued" ? <LiveDot /> : isManagedSession(row) && card ? <Mascot seed={card.mascot.seed} shape={card.mascot.style} name={card.name} size="sm" /> : <Icon name="chat" className="h-3 w-3 text-ink-muted" />}
    </span>
  );
}

function When({ row }: { row: SessionRow }) {
  const time = useTimeOnly();
  const day = useShortDate();
  const today = new Date(row.updated).toDateString() === new Date().toDateString();
  return <span className="w-guide text-right text-sm tabular-nums text-ink-faint">{today ? time(row.updated) : day(row.updated)}</span>;
}

function Session({ row }: { row: SessionRow }) {
  const assistant = useAssistant();
  const archive = useArchiveSession();
  const state = SESSION_STATES[row.status];
  return (
    <ContextMenu items={[{ id: "open", label: t("menu.open"), onSelect: () => assistant.openSession(row.id) }, ...(!isManagedSession(row) ? [{ id: "archive", label: t("menu.archive"), icon: "archive" as const, onSelect: () => archive.mutate(row.id) }] : [])]}>
      <ListRow
        testid="session-row"
        state={row.status}
        lead={<Lead row={row} />}
        title={row.title}
        meta={row.preview ?? (isManagedSession(row) ? t("chat.managed.badge") : null)}
        onOpen={() => assistant.openSession(row.id)}
        trailing={
          <>
            {row.status === "waiting" ? <span className="rounded-full bg-surface-sunken px-2 py-1 text-sm font-medium text-agent-waiting">{t("switcher.yourAnswer")}</span> : null}
            {row.status === "failed" && state ? <span className="text-sm text-status-danger">{t(state.label)}</span> : null}
            <When row={row} />
          </>
        }
      />
    </ContextMenu>
  );
}

export function SessionsScreen() {
  const assistant = useAssistant();
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const sessions = useSessions(search);
  const rows = sessions.data?.sessions ?? [];
  const groups = groupSessions(rows);
  const show = (group: keyof typeof groups) => filter === "all" || (filter === "waiting" && group === "waiting") || (filter === "agents" && group === "agents");
  const sections: { key: keyof typeof groups; title: StringKey; tone?: "waiting" }[] = [
    { key: "waiting", title: "sessions.waitingOnYou", tone: "waiting" },
    { key: "agents", title: "switcher.agents" },
    { key: "today", title: "switcher.today" },
    { key: "earlier", title: "switcher.earlier" },
  ];
  const shown = sections.filter((section) => show(section.key) && groups[section.key].length);
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-5 p-6">
      <PageHeader
        title={t("nav.sessions")}
        summary={sessions.data ? [tn("sessions.count", rows.length), groups.waiting.length ? tn("sessions.waitingCount", groups.waiting.length) : null, t("sessions.running", { running: sessions.data.running, limit: sessions.data.limit })].filter(Boolean).join(" · ") : undefined}
        action={<Button variant="primary" onClick={assistant.newChat}><Icon name="newChat" className="h-4 w-4" />{t("sessions.new")}</Button>}
      />
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <Input aria-label={t("sessions.search")} placeholder={t("sessions.search")} value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
        <Segmented hideLabel label={t("sessions.show")} value={filter} onChange={setFilter} options={[{ value: "all", label: t("sessions.filter.all") }, { value: "waiting", label: t("sessions.filter.waiting") }, { value: "agents", label: t("switcher.agents") }]} />
      </div>
      {sessions.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {sessions.isError ? <ErrorState title={t("sessions.error")} onRetry={() => void sessions.refetch()} /> : null}
      {sessions.isSuccess && (rows.length === 0 || shown.length === 0) ? <EmptyState icon="sessions" title={t("sessions.empty.title")} description={t("sessions.empty.description")} /> : null}
      {shown.map((section) => (
        <ListGroup key={section.key} title={t(section.title)} {...(section.tone ? { tone: section.tone } : {})}>
          {groups[section.key].map((row) => <Session key={row.id} row={row} />)}
        </ListGroup>
      ))}
    </div>
  );
}
