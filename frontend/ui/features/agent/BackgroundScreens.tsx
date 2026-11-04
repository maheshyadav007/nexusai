"use client";

import type { AgentEntry } from "@/ui/client/contracts.generated";
import { useDateTime, useRelativeTime } from "@/ui/client/format";
import { useActivity, useAgentChannel, useAgents, useMuteTopic, useUndo } from "@/ui/client/work";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { PageHeader } from "@/ui/primitives/PageHeader";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { Tabs } from "@/ui/primitives/Tabs";
import { SessionLink } from "@/ui/features/assistant/SessionLink";
import { t, type StringKey } from "@/ui/strings";

export function ActivityScreen() {
  const activity = useActivity();
  const undo = useUndo();
  const format = useDateTime();
  const rows = activity.data?.items ?? [];
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-5 p-6">
      <PageHeader title={t("nav.activity")} />
      {activity.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {activity.isError ? <ErrorState title={t("activity.error")} onRetry={() => void activity.refetch()} /> : null}
      {activity.isSuccess && rows.length === 0 ? <EmptyState icon="activity" title={t("activity.empty")} /> : null}
      <ul aria-label={t("nav.activity")} className="flex flex-col gap-px">
        {rows.map((item) => (
          <li key={item.id} data-testid="activity" className="flex items-center justify-between gap-3 border-b border-line-subtle py-2">
            <span className="min-w-0">
              <span className="block break-words text-md text-ink-primary">{item.summary}</span>
              <span className="text-sm tabular-nums text-ink-muted">{format(item.time)}</span>
            </span>
            {item.undoable ? <Button loading={undo.isPending} onClick={() => undo.mutate(item.id)}>{t("activity.undo")}</Button> : <span className="shrink-0 text-sm text-ink-muted">{t(item.undone ? "activity.undone" : "activity.notUndoable")}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

const STATE_LABEL: Readonly<Record<string, StringKey>> = { failed: "agents.state.failed", running: "agents.state.running", active: "agents.state.active", finished: "agents.state.finished", off: "agents.state.off", past: "agents.state.past" };
const STATE_TONE: Readonly<Record<string, "running" | "done" | "waiting" | "failed">> = { failed: "failed", running: "running", active: "done" };

function AgentCard({ agent }: { agent: AgentEntry }) {
  const format = useDateTime();
  const relative = useRelativeTime();
  const nextWhen = agent.next_run ? t("agents.next", { when: format(agent.next_run) }) : null;
  const next = [nextWhen, agent.next_condition].filter(Boolean).join(" · ");
  return (
    <li data-testid="agent-entry" data-state={agent.state} className="flex flex-col gap-1 border-b border-line-subtle py-3">
      <div className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-2">
          {STATE_TONE[agent.state] ? <StatusDot tone={STATE_TONE[agent.state] as "running" | "done"} /> : null}
          <span className="truncate text-md font-medium text-ink-primary">{agent.name}</span>
        </span>
        <Badge>{t(STATE_LABEL[agent.state] as StringKey)}</Badge>
      </div>
      <p className="text-sm text-ink-secondary">{agent.does}</p>
      <p className="text-sm text-ink-primary">{agent.when}</p>
      {next ? <p data-testid="agent-next" className="text-sm tabular-nums text-accent-default">{next}</p> : null}
      <p className="flex flex-wrap items-center gap-2 text-sm tabular-nums text-ink-muted">
        {agent.last_run ? t("agents.last", { when: relative(agent.last_run) }) : agent.state === "finished" ? null : t("agents.never")}
        {agent.tokens ? <span>· {t("agents.tokens", { count: agent.tokens.toLocaleString() })}</span> : null}
        {agent.session ? <SessionLink className="text-sm" session={agent.session}>{t("agents.open")}</SessionLink> : null}
      </p>
    </li>
  );
}

function AgentList() {
  const agents = useAgents();
  const rows = agents.data?.agents ?? [];
  if (agents.isPending) return <Skeleton className="h-6 w-full" />;
  if (agents.isError) return <ErrorState title={t("agents.error")} onRetry={() => void agents.refetch()} />;
  if (!rows.length) return <EmptyState icon="agent" title={t("agents.empty")} />;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-md text-ink-secondary">{t("agents.description")}</p>
      <ul aria-label={t("agents.title")} className="flex flex-col border-t border-line-subtle">
        {rows.map((agent) => <AgentCard key={agent.id} agent={agent} />)}
      </ul>
    </div>
  );
}

export function AgentChannelScreen() {
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-5 p-6">
      <PageHeader title={t("nav.channel")} />
      <Tabs label={t("nav.channel")} tabs={[{ value: "agents", label: t("agents.title"), content: <AgentList /> }, { value: "messages", label: t("agents.messages"), content: <ChannelMessages /> }]} />
    </div>
  );
}

function ChannelMessages() {
  const channel = useAgentChannel();
  const mute = useMuteTopic();
  const format = useDateTime();
  const rows = channel.data?.messages ?? [];
  const muted = channel.data?.muted ?? [];
  return (
    <div className="flex flex-col gap-5">
      <p className="text-md text-ink-secondary">{t("agentChannel.description")}</p>
      {channel.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {channel.isError ? <ErrorState title={t("agentChannel.error")} onRetry={() => void channel.refetch()} /> : null}
      {channel.isSuccess && rows.length === 0 ? <EmptyState icon="channel" title={t("agentChannel.empty")} /> : null}
      {muted.length ? (
        <div className="flex flex-wrap items-center gap-2 text-sm text-ink-muted">
          {t("agentChannel.muted")}
          {muted.map((topic) => <Button key={topic} variant="quiet" className="py-px" onClick={() => mute.mutate({ topic, muted: false })}>{topic}</Button>)}
        </div>
      ) : null}
      <ul aria-label={t("nav.channel")} className="flex flex-col gap-2">
        {rows.map((message) => (
          <li key={message.id} data-testid="agent-message-row" className="flex flex-col gap-1 rounded-md border border-line-subtle p-3">
            <span className="flex flex-wrap items-center gap-2 text-sm text-ink-muted">
              <span className="tabular-nums">{format(message.time)}</span>
              {message.topic ? <Badge>{message.topic}</Badge> : null}
              {message.purpose ? <p className="text-sm text-ink-secondary">{message.state} · {message.purpose}</p> : null}
              {message.expected_output ? <p className="text-sm text-ink-secondary">{message.expected_output}</p> : null}
              {message.outcome ? <p className="text-md text-ink-primary">{message.outcome}</p> : null}
              {message.untrusted ? <Badge tone="warning">{t("agentChannel.untrusted")}</Badge> : null}
            </span>
            <p className="break-words text-md text-ink-primary">{message.text}</p>
            {message.topic ? <div><Button variant="quiet" className="py-px" onClick={() => mute.mutate({ topic: message.topic ?? "", muted: true })}>{t("agentChannel.mute")}</Button></div> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
