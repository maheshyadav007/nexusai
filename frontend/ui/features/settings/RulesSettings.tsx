"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { MailRule, RuleCondition } from "@/ui/client/contracts.generated";
import { useRules, useSaveRules } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Switch } from "@/ui/primitives/Switch";
import { useToast } from "@/ui/primitives/Toast";
import { t, tn } from "@/ui/strings";

const FIELDS = [
  { value: "subject", label: t("rules.field.subject") },
  { value: "subject_prefix", label: t("rules.field.subjectPrefix") },
  { value: "tag", label: t("rules.field.tag") },
  { value: "sender", label: t("rules.field.sender") },
  { value: "sender_exact", label: t("rules.field.senderExact") },
  { value: "body", label: t("rules.field.body") },
  { value: "header", label: t("rules.field.header") },
  { value: "has_attachment", label: t("rules.field.attachment") },
];

const emptyCondition = (): RuleCondition => ({ field: "subject", value: "" });
const emptyRule = (): MailRule => ({ name: t("rules.newName"), enabled: true, conditions: [emptyCondition()] as MailRule["conditions"], actions: { category: null, mark_read: false, skip_agent: false, notify: false, tag: null } });

/** One condition in words, the way a person would say it. */
export function phrase(condition: RuleCondition): string {
  const value = condition.value ?? "";
  switch (condition.field) {
    case "sender_exact": return t("rules.said.from", { sender: value });
    case "tag": return t("rules.said.tag", { tag: value });
    case "subject_prefix": return t("rules.said.startsWith", { value });
    case "subject": return t("rules.said.has", { value });
    case "has_attachment": return t("rules.field.attachment");
    case "header": return t("rules.said.header", { header: condition.header ?? "", value });
    default: return t("rules.matches", { field: FIELDS.find((item) => item.value === condition.field)?.label ?? condition.field, value });
  }
}

/** A whole rule in words: every condition it needs, joined. */
export function phraseRule(rule: MailRule): string {
  return rule.conditions.map(phrase).join(t("rules.said.and"));
}

function RuleEditor({ rule, onChange, onRemove, startsOpen }: { rule: MailRule; onChange: (rule: MailRule) => void; onRemove: () => void; startsOpen: boolean }) {
  const actions = rule.actions;
  const matching = rule.conditions
    .filter((condition) => condition.value || condition.field === "has_attachment")
    .map(phrase)
    .join(", ");
  const setCondition = (position: number, changes: Partial<RuleCondition>) => onChange({ ...rule, conditions: rule.conditions.map((item, i) => (i === position ? { ...item, ...changes } : item)) as MailRule["conditions"] });
  return (
    <ExpandRow
      testid="rule"
      label={t("rules.open", { name: rule.name })}
      defaultOpen={startsOpen}
      title={rule.name}
      meta={
        <>
          {t(rule.enabled === false ? "rules.off" : "rules.on")}
          {matching ? ` · ${matching}` : ""}
          {actions.category ? ` · ${t("rules.filesInto", { category: actions.category })}` : ""}
        </>
      }
      aside={<Switch label={t("rules.enabled")} hideLabel checked={rule.enabled ?? true} onChange={(enabled) => onChange({ ...rule, enabled })} />}
    >
      <div className="flex items-end gap-3">
        <div className="min-w-0 flex-1"><Field label={t("rules.name")}>{({ invalid, ...control }) => <Input invalid={invalid} value={rule.name} onChange={(event) => onChange({ ...rule, name: event.target.value })} {...control} />}</Field></div>
        <IconButton icon="close" label={t("rules.remove", { name: rule.name })} onClick={onRemove} />
      </div>
      <p className="text-md font-medium text-ink-primary">{t("rules.when")}</p>
      {rule.conditions.map((condition, position) => (
        <div key={position} className="grid gap-2 md:grid-cols-2">
          <Field label={t("rules.field")}>{({ invalid, id }) => <Select id={id} invalid={invalid} value={condition.field} options={FIELDS} onChange={(field) => setCondition(position, { field: field as RuleCondition["field"] })} />}</Field>
          {condition.field === "has_attachment" ? null : <Field label={t("rules.contains")}>{({ invalid, ...control }) => <Input invalid={invalid} value={condition.value ?? ""} onChange={(event) => setCondition(position, { value: event.target.value })} {...control} />}</Field>}
          {condition.field === "header" ? <Field label={t("rules.header")}>{({ invalid, ...control }) => <Input invalid={invalid} value={condition.header ?? ""} onChange={(event) => setCondition(position, { header: event.target.value })} {...control} />}</Field> : null}
        </div>
      ))}
      <div><Button variant="quiet" onClick={() => onChange({ ...rule, conditions: [...rule.conditions, emptyCondition()] as MailRule["conditions"] })}>{t("rules.addCondition")}</Button></div>
      <p className="text-md font-medium text-ink-primary">{t("rules.then")}</p>
      <Field label={t("rules.category")}>{({ invalid, ...control }) => <Input invalid={invalid} value={actions.category ?? ""} onChange={(event) => onChange({ ...rule, actions: { ...actions, category: event.target.value || null } })} {...control} />}</Field>
      <div className="flex flex-col gap-2">
        <Checkbox label={t("rules.markRead")} checked={actions.mark_read ?? false} onChange={(mark_read) => onChange({ ...rule, actions: { ...actions, mark_read } })} />
        <Checkbox label={t("rules.skipAgent")} checked={actions.skip_agent ?? false} onChange={(skip_agent) => onChange({ ...rule, actions: { ...actions, skip_agent } })} />
        <Checkbox label={t("rules.notify")} checked={actions.notify ?? false} onChange={(notify) => onChange({ ...rule, actions: { ...actions, notify } })} />
      </div>
    </ExpandRow>
  );
}

// What the Sort step and "Move to Inbox" write. They show by folder, in words, not one row each.
const SORTED = "Sorted: ";
const READS = "AI reads: ";
const written = (rule: MailRule) => rule.name.startsWith(SORTED) || rule.name.startsWith(READS);

/** One rule the app wrote, as a sentence: what it matches. */
function said(rule: MailRule): string {
  return rule.conditions.map(phrase).join(", ");
}

/** The rules sorting wrote for one folder: what goes there, and a way to take any one back. */
function WrittenGroup({ title, meta, rules, onRemove }: { title: string; meta: string; rules: readonly { rule: MailRule; index: number }[]; onRemove: (index: number) => void }) {
  return (
    <ExpandRow testid="rule-group" label={t("rules.open", { name: title })} title={title} meta={meta}>
      <ul className="flex flex-col">
        {rules.map(({ rule, index }) => (
          <li key={rule.name} data-testid="written-rule" className="flex items-center gap-3 border-t border-line-subtle py-2 first:border-t-0">
            <span className="min-w-0 flex-1 break-words text-sm text-ink-secondary">{said(rule)}</span>
            <IconButton icon="close" label={t("rules.remove", { name: rule.name })} onClick={() => onRemove(index)} />
          </li>
        ))}
      </ul>
    </ExpandRow>
  );
}

export function RulesSettings() {
  const router = useRouter();
  const toast = useToast();
  const saved = useRules();
  const save = useSaveRules();
  const [rules, setRules] = useState<MailRule[] | null>(null);
  useEffect(() => {
    if (saved.data && rules === null) setRules(saved.data.rules);
  }, [saved.data, rules]);
  const indexed = (rules ?? []).map((rule, index) => ({ rule, index }));
  const own = indexed.filter(({ rule }) => !written(rule));
  const reads = indexed.filter(({ rule }) => rule.name.startsWith(READS));
  const folders = new Map<string, { rule: MailRule; index: number }[]>();
  for (const item of indexed) if (item.rule.name.startsWith(SORTED)) folders.set(item.rule.actions.category ?? "", [...(folders.get(item.rule.actions.category ?? "") ?? []), item]);
  const remove = (index: number) => setRules((rules ?? []).filter((_, i) => i !== index));
  return (
    <Card title={t("settings.section.rules")} description={t("rules.description")}>
      <div className="flex flex-col gap-4">
        {saved.isError ? <ErrorState title={t("rules.error")} onRetry={() => void saved.refetch()} /> : null}
        {rules === null && saved.isPending ? <Skeleton className="h-6 w-full" /> : null}
        {rules?.length === 0 ? <EmptyState icon="categories" title={t("rules.empty")} /> : null}
        {reads.length || folders.size ? (
          <section aria-label={t("rules.written")} className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-md font-medium text-ink-primary">{t("rules.written")}</h3>
              <Button variant="quiet" onClick={() => router.push("/mail/sort")}>{t("rules.sortAgain")}</Button>
            </div>
            <p className="text-sm text-ink-muted">{t("rules.written.hint")}</p>
            {reads.length ? <WrittenGroup title={t("rules.reads")} meta={tn("rules.reads.meta", reads.length)} rules={reads} onRemove={remove} /> : null}
            {[...folders.entries()].map(([folder, items]) => <WrittenGroup key={folder} title={folder} meta={tn("rules.folder.meta", items.filter(({ rule }) => rule.conditions.some((c) => c.field === "sender_exact")).length)} rules={items} onRemove={remove} />)}
          </section>
        ) : null}
        {own.length ? <h3 className="text-md font-medium text-ink-primary">{t("rules.own")}</h3> : null}
        {own.map(({ rule, index }) => (
          <RuleEditor key={index} rule={rule} startsOpen={index >= (saved.data?.rules.length ?? 0)} onChange={(next) => setRules((rules ?? []).map((item, i) => (i === index ? next : item)))} onRemove={() => remove(index)} />
        ))}
        {save.isError ? <ErrorState title={t("rules.saveError")} description={save.error instanceof ApiRequestError ? save.error.detail.message : ""} /> : null}
        <div className="flex gap-2">
          <Button onClick={() => setRules([...(rules ?? []), emptyRule()])}>{t("rules.add")}</Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate({ rules: rules ?? [] }, { onSuccess: () => toast({ title: t("rules.saved") }) })}>{t("settings.save")}</Button>
        </div>
      </div>
    </Card>
  );
}
