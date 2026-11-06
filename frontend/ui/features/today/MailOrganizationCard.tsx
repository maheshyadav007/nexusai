"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { command, query } from "@/ui/client/api";
import type { Importance, MergeCategories } from "@/ui/client/contracts.generated";
import { useHomeReady } from "@/ui/client/home";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Select } from "@/ui/primitives/Select";
import { TextLink } from "@/ui/primitives/TextLink";
import { t } from "@/ui/strings";

/** One review for new uncertainty; cached sender groups do not ask again. */
export function MailOrganizationCard() {
  const ready = useHomeReady();
  const client = useQueryClient();
  const organization = useQuery({ queryKey: ["mail-organization"], queryFn: () => query("mail.organization", {}), enabled: ready, refetchInterval: 5000 });
  const [choices, setChoices] = useState<Record<string, Importance>>({});
  const refresh = () => Promise.all([client.invalidateQueries({ queryKey: ["mail-organization"] }), client.invalidateQueries({ queryKey: ["categories"] }), client.invalidateQueries({ queryKey: ["threads"] }), client.invalidateQueries({ queryKey: ["today"] })]);
  const finish = useMutation({ mutationFn: (skip: boolean) => command("mail.learning.finish", { importance: skip ? {} : choices }), onSuccess: refresh });
  const merge = useMutation({ mutationFn: (input: MergeCategories) => command("categories.merge", input), onSuccess: refresh });
  const retry = useMutation({ mutationFn: () => command("mailAgent.retryLearning", {}), onSuccess: refresh });
  const data = organization.data ? { ...organization.data, merges: organization.data.merges ?? [], missed: organization.data.missed ?? [], groups: organization.data.groups ?? [], suggestions: organization.data.suggestions ?? [], done: organization.data.done ?? 0, total: organization.data.total ?? 0 } : null;
  if (!data || (!data.merges.length && !data.missed.length && !["learning", "asking", "failed"].includes(data.state))) return null;
  return <Card title={t("mail.organization.title")}>
    {data.state === "learning" ? <p role="status">{t("mail.organization.progress", { done: data.done, total: data.total })}</p> : null}
    {data.state === "failed" ? <ErrorState title={t("mail.organization.failed")} onRetry={() => retry.mutate()} /> : null}
    {data.state === "asking" ? <div className="flex flex-col gap-3">
      {data.interview ? <TextLink href={`/agent/sessions/${data.interview}`}>{t("mail.organization.interview")}</TextLink> : null}
      {data.groups.map((group) => <Select key={group.id} label={`${group.sender}: ${group.subject}`} value={choices[group.id] ?? group.importance} options={[{ value: "low", label: t("mail.importance.low") }, { value: "normal", label: t("mail.importance.normal") }, { value: "high", label: t("mail.importance.high") }]} onChange={(value) => setChoices((current) => ({ ...current, [group.id]: value as Importance }))} />)}
      {data.suggestions.map((folder) => <p key={folder.name}>{t("mail.organization.suggestion", { name: folder.name, senders: folder.senders, emails: folder.emails })}</p>)}
      <div className="flex flex-wrap gap-2">
        <Button loading={finish.isPending} onClick={() => finish.mutate(false)}>{t("mail.organization.continue")}</Button>
        <Button variant="quiet" disabled={finish.isPending} onClick={() => finish.mutate(true)}>{t("mail.organization.skip")}</Button>
      </div>
    </div> : null}
    {data.missed.length ? <details><summary>{t("mail.organization.missed", { count: data.missed.length })}</summary><ul>{data.missed.map((thread) => <li key={thread.id}><TextLink href={`/mail/thread/${thread.id}`}>{thread.subject}</TextLink></li>)}</ul></details> : null}
    {data.merges.map((suggestion) => <div key={suggestion.into} className="flex items-center justify-between gap-3"><span>{t("mail.organization.merges", { names: suggestion.names.join(", "), into: suggestion.into })}</span><Button loading={merge.isPending} onClick={() => merge.mutate({ into: suggestion.into, names: suggestion.names as [string, ...string[]] })}>{t("mail.organization.merge")}</Button></div>)}
    {finish.error || merge.error || retry.error ? <ErrorState title={(finish.error ?? merge.error ?? retry.error)!.message} /> : null}
  </Card>;
}
