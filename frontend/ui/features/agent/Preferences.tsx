"use client";

import { useState } from "react";
import type { Preference, SavePreference } from "@/ui/client/contracts.generated";
import { usePreferences, useSavePreference, usePreferenceHistory, useRestorePreference, usePreferencePreview, useSimulatePreference } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { TextEditor } from "@/ui/primitives/TextView";
import { GenerationSurface } from "@/ui/primitives/GenerationSurface";
import { useMailAccounts } from "@/ui/client/mail";
import { TextLink } from "@/ui/primitives/TextLink";
import { t } from "@/ui/strings";

function PreferenceHistory({ item }: { item: Preference }) {
  const history = usePreferenceHistory(item.id);
  const restore = useRestorePreference();
  return <div className="flex flex-col gap-3">
    {history.isPending ? <Skeleton className="h-6 w-full" /> : null}
    {history.isError || restore.isError ? <ErrorState title={t("preferences.failed")} /> : null}
    {history.data?.evidence?.map((event,index) => <div key={index} className="border-t border-line-subtle pt-3 text-sm text-ink-secondary">
      <p>{event.time.slice(0,10)} · {event.action}</p>
      <p>{event.old_value} → {event.new_value}</p>
      {event.artifact === "thread" ? <TextLink href={`/mail/all/${event.artifact_id}`}>{t("preferences.evidence.open")}</TextLink> : null}
    </div>)}
    {history.data?.versions.map(version => <div key={version.revision} className="flex flex-col gap-2 border-t border-line-subtle pt-3">
      <p className="text-sm text-ink-muted">{t("preferences.version", { version: version.revision })} · {version.status}</p>
      <p className="whitespace-pre-wrap text-md text-ink-primary">{version.instruction}</p>
      {version.revision !== item.revision ? <div><Button loading={restore.isPending} onClick={() => restore.mutate({id:item.id, revision:item.revision, restore_revision:version.revision})}>{t("preferences.restore")}</Button></div> : null}
    </div>)}
  </div>;
}

function PreferenceEditor({ item, onSaved }: { item?: Preference; onSaved?: () => void }) {
  const save = useSavePreference();
  const preview = usePreferencePreview();
  const simulate = useSimulatePreference();
  const accounts = useMailAccounts();
  const [instruction, setInstruction] = useState(item?.instruction ?? "");
  const [purpose, setPurpose] = useState<SavePreference["purpose"]>(item?.purpose ?? "all");
  const [account, setAccount] = useState(item?.account ?? "");
  const [sender, setSender] = useState(item?.sender ?? "");
  const [topic, setTopic] = useState(item?.topic ?? "");
  const [expires, setExpires] = useState(item?.expires_at?.slice(0,10) ?? "");
  const value = (status: SavePreference["status"] = "active"): SavePreference => ({
    ...(item ? {id:item.id, revision:item.revision} : {}), instruction:instruction.trim(), purpose,
    account:account.trim() || null, sender:sender.trim() || null, topic:topic.trim() || null,
    expires_at:expires ? `${expires}T23:59:59Z` : null, status, evidence:item?.evidence ?? [],
  });
  const current = JSON.stringify(value());
  const scopeIsCurrent = preview.variables && JSON.stringify(preview.variables) === current;
  const simulationIsCurrent = simulate.variables && JSON.stringify(simulate.variables) === current;
  return <form className="flex flex-col gap-3" onSubmit={event => {event.preventDefault(); save.mutate(value(), {onSuccess:onSaved});}}>
    <TextEditor label={t("preferences.instruction")} value={instruction} onChange={setInstruction} rows={3} />
    <Select label={t("preferences.purpose")} value={purpose} onChange={next => setPurpose(next as SavePreference["purpose"])} options={(["all","mail","draft","brief"] as const).map(p => ({value:p,label:t(`preferences.purpose.${p}`)}))} />
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <Field label={t("preferences.account")} hint={t("preferences.account.hint")}>{({invalid,id}) => <Select id={id} invalid={invalid} value={account || "all"} onChange={next => setAccount(next === "all" ? "" : next)} options={[{value:"all",label:t("preferences.account.all")},...(accounts.data?.accounts ?? []).map(item => ({value:item.name,label:item.profile.label || item.name}))]} />}</Field>
      <Field label={t("preferences.sender")} hint={t("preferences.sender.hint")}>{({invalid,...control}) => <Input {...control} invalid={invalid} value={sender} onChange={event => setSender(event.target.value)} />}</Field>
      <Field label={t("preferences.topic")} hint={t("preferences.topic.hint")}>{({invalid,...control}) => <Input {...control} invalid={invalid} value={topic} onChange={event => setTopic(event.target.value)} />}</Field>
      <Field label={t("preferences.expires")} hint={t("preferences.expires.hint")}>{({invalid,...control}) => <Input {...control} invalid={invalid} type="date" value={expires} onChange={event => setExpires(event.target.value)} />}</Field>
    </div>
    {preview.data && scopeIsCurrent ? <div role="status" className="rounded-md border border-line-subtle p-3 text-sm text-ink-secondary"><p>{t("preferences.preview.count", {matched:preview.data.matched,total:preview.data.total})}</p><p>{t("preferences.preview.hint")}</p><ul className="mt-2 list-inside list-disc">{preview.data.examples.map((subject,index) => <li key={index}>{subject}</li>)}</ul></div> : null}
    {simulate.isPending ? <GenerationSurface phase={simulate.phase} label={t("preferences.simulating")} placeholder /> : null}
    {simulate.data && simulationIsCurrent ? <div className="flex flex-col gap-3 rounded-md border border-line-subtle p-3"><p className="text-sm text-ink-muted">{t("preferences.simulation.hint")}</p>{simulate.data.decisions.length === 0 ? <p>{t("preferences.simulation.empty")}</p> : null}{simulate.data.decisions.map(result => <div key={result.thread} className="border-t border-line-subtle pt-3"><TextLink href={`/mail/all/${result.thread}`}>{result.subject}</TextLink><p className="text-sm text-ink-secondary">{result.before} → {result.after}</p><p className="text-md text-ink-primary">{result.reason}</p></div>)}</div> : null}
    {simulate.isError ? <ErrorState title={t("preferences.failed")} description={simulate.error.message} /> : null}
    {save.isError || preview.isError ? <ErrorState title={t("preferences.failed")} description={save.error?.message ?? preview.error?.message} /> : null}
    <div className="flex flex-wrap gap-2">
      <Button type="submit" variant="primary" disabled={!instruction.trim()} loading={save.isPending}>{t(item?.status === "proposed" ? "preferences.approve" : "preferences.save")}</Button>
      <Button disabled={!instruction.trim()} loading={preview.isPending} onClick={() => preview.mutate(value())}>{t("preferences.preview")}</Button>
      {purpose === "mail" || purpose === "all" ? <Button variant="ai" disabled={!instruction.trim()} loading={simulate.isPending} onClick={() => simulate.mutate(value())}>{t("preferences.simulate")}</Button> : null}
      {item?.status === "proposed" ? <Button loading={save.isPending} onClick={() => save.mutate(value("declined"))}>{t("preferences.decline")}</Button> : item?.status === "active" ? <Button loading={save.isPending} onClick={() => save.mutate(value("retired"))}>{t("preferences.retire")}</Button> : null}
    </div>
  </form>;
}

export function Preferences() {
  const preferences = usePreferences();
  const [adding,setAdding] = useState(false);
  if (preferences.isPending) return <Skeleton className="h-6 w-full" />;
  if (preferences.isError) return <ErrorState title={t("preferences.failed")} onRetry={() => void preferences.refetch()} />;
  return <div className="flex flex-col gap-4" data-testid="preferences">
    <p className="text-md text-ink-secondary">{t("preferences.description")}</p>
    <div><Button aria-expanded={adding} onClick={() => setAdding(!adding)}>{t(adding ? "preferences.cancel" : "preferences.add")}</Button></div>
    {adding ? <PreferenceEditor onSaved={() => setAdding(false)} /> : null}
    {preferences.data.preferences.length === 0 ? <EmptyState icon="memory" title={t("preferences.empty")} /> : null}
    {preferences.data.preferences.map(item => <ExpandRow key={`${item.id}-${item.revision}`} defaultOpen={item.status === "proposed"} label={t("preferences.edit")} title={item.instruction} meta={t(`preferences.status.${item.status}`) + " · " + t(`preferences.purpose.${item.purpose}`)}>
      {(item.evidence?.length ?? 0) ? <p className="mb-3 text-sm text-ink-muted">{t("preferences.evidence", {count:(item.evidence?.length ?? 0)})}</p> : null}
      <PreferenceEditor item={item} />
      <ExpandRow label={t("preferences.history")} title={t("preferences.history")}><PreferenceHistory item={item} /></ExpandRow>
    </ExpandRow>)}
  </div>;
}
