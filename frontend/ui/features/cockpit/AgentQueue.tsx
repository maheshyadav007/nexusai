"use client";

import { useAgentQueue, useQueueAction } from "@/ui/client/work";
import { useRelativeTime } from "@/ui/client/format";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { SessionLink } from "@/ui/features/assistant/SessionLink";
import { t } from "@/ui/strings";

export function AgentQueue() {
  const queue = useAgentQueue();
  const act = useQueueAction();
  const relative = useRelativeTime();
  if (queue.isError) return <ErrorState title={t("queue.error")} onRetry={() => void queue.refetch()} />;
  if (!queue.data || !queue.data.items.length) return null;
  return <Card title={t("queue.title")} description={t("queue.count",{pending:queue.data.pending,running:queue.data.running,failed:queue.data.failed})}>
    {queue.data.oldest_pending ? <p className="mb-3 text-sm text-ink-muted">{t("queue.oldest",{when:relative(queue.data.oldest_pending)})}</p> : null}
    {act.isError ? <ErrorState title={t("queue.error")} description={act.error.message} /> : null}
    <ul className="divide-y divide-line-subtle">{queue.data.items.map(item => <li key={item.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
      <div className="min-w-0 flex-1"><p className="text-md text-ink-primary">{item.title}</p><p className="text-sm text-ink-muted">{item.status} · {relative(item.time)}</p>{item.error ? <p className="break-words text-sm text-ink-secondary">{item.error}</p> : null}</div>
      <div className="flex items-center gap-2">{item.session ? <SessionLink session={item.session} className="text-sm">{t("channel.openSession")}</SessionLink> : null}{item.status === "failed" ? <Button loading={act.isPending} onClick={() => act.mutate({id:item.id,action:"retry"})}>{t("queue.retry")}</Button> : item.status === "pending" ? <Button loading={act.isPending} onClick={() => act.mutate({id:item.id,action:"cancel"})}>{t("queue.cancel")}</Button> : null}</div>
    </li>)}</ul>
  </Card>;
}
