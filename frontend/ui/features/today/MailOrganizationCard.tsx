"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { command, query } from "@/ui/client/api";
import type { Importance, MergeCategories } from "@/ui/client/contracts.generated";
import { useHomeReady, useLeadName } from "@/ui/client/home";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Select } from "@/ui/primitives/Select";
import { TextLink } from "@/ui/primitives/TextLink";
import { t } from "@/ui/strings";

/** One review for new uncertainty; cached sender groups do not ask again. Every guess is shown
 * with its reason, so keeping the guesses is a choice the person can see. Suggested folders are
 * decided under "For your decision", so they aren't repeated here. */
export function MailOrganizationCard() {
  const ready = useHomeReady();
  const lead = useLeadName();
  const client = useQueryClient();
  const organization = useQuery({ queryKey: ["mail-organization"], queryFn: () => query("mail.organization", {}), enabled: ready, refetchInterval: 5000 });
  const [choices, setChoices] = useState<Record<string, Importance>>({});
  const refresh = () => Promise.all([client.invalidateQueries({ queryKey: ["mail-organization"] }), client.invalidateQueries({ queryKey: ["categories"] }), client.invalidateQueries({ queryKey: ["threads"] }), client.invalidateQueries({ queryKey: ["today"] })]);
  const finish = useMutation({ mutationFn: (keep: boolean) => command("mail.learning.finish", { importance: keep ? {} : choices }), onSuccess: refresh });
  const merge = useMutation({ mutationFn: (input: MergeCategories) => command("categories.merge", input), onSuccess: refresh });
  const data = organization.data ? { ...organization.data, merges: organization.data.merges ?? [], missed: organization.data.missed ?? [], groups: organization.data.groups ?? [] } : null;
  // Reading progress and a failed read show in Getting started; this card is for answering.
  if (!data || (!data.merges.length && !data.missed.length && data.state !== "asking")) return null;
  const changed = Object.keys(choices).length > 0;
  return <Card title={t("mail.organization.title")}>
    <div className="flex flex-col gap-6">
      {data.state === "asking" ? <section className="flex flex-col gap-3">
        <h3 className="text-md font-medium text-ink-primary">{t("mail.organization.senders.title")}</h3>
        <p className="text-sm text-ink-muted">{t(data.groups.length ? "mail.organization.senders.intro" : "mail.organization.senders.none", { name: lead })}</p>
        {data.groups.length ? <ul className="flex flex-col">
          {data.groups.map((group) => <li key={group.id} className="flex flex-col gap-2 border-b border-line-subtle py-3 last:border-b-0 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
            <span className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="truncate text-md text-ink-primary">{group.sender}</span>
              {group.subject ? <span className="truncate text-sm text-ink-secondary">{group.subject}</span> : null}
              {group.note ? <span className="text-sm text-ink-muted">{t("mail.organization.senders.why", { name: lead, note: group.note })}</span> : null}
            </span>
            <span className="w-full shrink-0 sm:w-rail-wide">
              <Select compact label={t("mail.organization.senders.choice", { sender: group.sender })} value={choices[group.id] ?? group.importance} options={[{ value: "high", label: t("mail.importance.high") }, { value: "normal", label: t("mail.importance.normal") }, { value: "low", label: t("mail.importance.low") }]} onChange={(value) => setChoices((current) => ({ ...current, [group.id]: value as Importance }))} />
            </span>
          </li>)}
        </ul> : null}
        <div className="flex flex-wrap gap-2">
          {changed ? <Button variant="primary" loading={finish.isPending} onClick={() => finish.mutate(false)}>{t("mail.organization.save")}</Button> : null}
          <Button variant={changed ? "quiet" : "primary"} loading={!changed && finish.isPending} disabled={changed && finish.isPending} onClick={() => (changed ? setChoices({}) : finish.mutate(true))}>{t(changed ? "mail.organization.discard" : data.groups.length ? "mail.organization.keep" : "mail.organization.finish", { name: lead })}</Button>
        </div>
      </section> : null}
      {data.missed.length ? <section className="flex flex-col gap-2">
        <h3 className="text-md font-medium text-ink-primary">{t("mail.organization.missed.title")}</h3>
        <p className="text-sm text-ink-muted">{t("mail.organization.missed.intro", { count: data.missed.length })}</p>
        <details><summary className="focus-ring w-fit cursor-pointer rounded-md text-sm text-accent-primary">{t("mail.organization.missed.show")}</summary><ul className="mt-2 flex flex-col gap-1">{data.missed.map((thread) => <li key={thread.id}><TextLink href={`/mail/thread/${thread.id}`}>{thread.subject}</TextLink></li>)}</ul></details>
      </section> : null}
      {data.merges.length ? <section className="flex flex-col gap-2">
        <h3 className="text-md font-medium text-ink-primary">{t("mail.organization.merges.title")}</h3>
        {data.merges.map((suggestion) => <div key={suggestion.into} className="flex items-center justify-between gap-3"><span className="text-sm text-ink-secondary">{t("mail.organization.merges", { names: suggestion.names.join(", "), into: suggestion.into })}</span><Button loading={merge.isPending} onClick={() => merge.mutate({ into: suggestion.into, names: suggestion.names as [string, ...string[]] })}>{t("mail.organization.merge")}</Button></div>)}
      </section> : null}
      {finish.error || merge.error ? <ErrorState title={(finish.error ?? merge.error)!.message} /> : null}
    </div>
  </Card>;
}
