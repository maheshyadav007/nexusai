"use client";

import { useDateTime } from "@/ui/client/format";
import { useActivity, useAgentChannel, useMuteTopic, useUndo } from "@/ui/client/work";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { PageHeader } from "@/ui/primitives/PageHeader";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";

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

export function AgentChannelScreen() {
  const channel = useAgentChannel();
  const mute = useMuteTopic();
  const format = useDateTime();
  const rows = channel.data?.messages ?? [];
  const muted = channel.data?.muted ?? [];
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-5 p-6">
      <PageHeader title={t("nav.channel")} summary={t("agentChannel.description")} />
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
