"use client";

import Link from "next/link";
import { useDateTime } from "@/ui/client/format";
import { useMailStatus } from "@/ui/client/mail";
import { useActivity, useAgentChannel, useJobs, useMuteTopic, useTriageEstimate, useTriageExisting, useUndo } from "@/ui/client/work";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Progress } from "@/ui/primitives/Progress";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { t, tn } from "@/ui/strings";

export function BackgroundScreen() {
  const jobs = useJobs();
  const mail = useMailStatus();
  const estimate = useTriageEstimate();
  const triage = useTriageExisting();
  const rows = jobs.data?.jobs ?? [];
  const untriaged = estimate.data?.untriaged ?? 0;
  return (
    <div className="mx-auto flex max-w-content flex-col gap-4 p-6">
      <h1 className="font-serif text-display text-ink-primary">{t("nav.background")}</h1>
      {mail.data && mail.data.state !== "off" ? (
        <p role="status" className="flex items-center gap-2 text-md text-ink-secondary">
          <StatusDot tone={mail.data.state === "live" ? "done" : mail.data.state === "failed" || mail.data.state === "offline" ? "failed" : "running"} />
          {tn(mail.data.state === "live" ? "background.mail.live" : "background.mail.syncing", mail.data.messages ?? 0)}
        </p>
      ) : null}
      {jobs.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {jobs.isError ? <ErrorState title={t("background.error")} onRetry={() => void jobs.refetch()} /> : null}
      {jobs.isSuccess && rows.length === 0 ? <EmptyState icon="background" title={t("background.empty")} /> : null}
      <ul aria-label={t("nav.background")} className="flex flex-col gap-2">
        {rows.map((job) => (
          <li key={job.id} data-testid="job">
            <Link href={job.link ?? "/agent/background"} className="focus-ring flex flex-col gap-2 rounded-md border border-line-subtle p-3 transition-colors duration-fast hover:bg-surface-sunken">
              <span className="flex items-center justify-between gap-3 text-md">
                <span className="min-w-0 truncate text-ink-primary">{job.title}</span>
                <span className="shrink-0 text-sm text-ink-secondary">{job.status}</span>
              </span>
              {job.progress != null && job.total ? <Progress label={job.title} value={job.progress} max={job.total} /> : null}
            </Link>
          </li>
        ))}
      </ul>
      {untriaged > 0 ? (
        <Card title={t("background.older")} description={tn("background.older.description", untriaged, { tokens: (estimate.data?.approx_tokens ?? 0).toLocaleString() })}>
          <Button loading={triage.isPending} onClick={() => triage.mutate(true)}>{t("background.older.action")}</Button>
        </Card>
      ) : null}
    </div>
  );
}

export function ActivityScreen() {
  const activity = useActivity();
  const undo = useUndo();
  const format = useDateTime();
  const rows = activity.data?.items ?? [];
  return (
    <div className="mx-auto flex max-w-content flex-col gap-4 p-6">
      <h1 className="font-serif text-display text-ink-primary">{t("nav.activity")}</h1>
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
    <div className="mx-auto flex max-w-content flex-col gap-4 p-6">
      <header>
        <h1 className="font-serif text-display text-ink-primary">{t("nav.channel")}</h1>
        <p className="mt-1 text-md text-ink-muted">{t("agentChannel.description")}</p>
      </header>
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
