"use client";

import { useEffect, useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { MailRule, RuleCondition } from "@/ui/client/contracts.generated";
import { useRules, useSaveRules } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Switch } from "@/ui/primitives/Switch";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";

const FIELDS = [
  { value: "subject", label: t("rules.field.subject") },
  { value: "sender", label: t("rules.field.sender") },
  { value: "body", label: t("rules.field.body") },
  { value: "header", label: t("rules.field.header") },
  { value: "has_attachment", label: t("rules.field.attachment") },
];

const emptyCondition = (): RuleCondition => ({ field: "subject", value: "" });
const emptyRule = (): MailRule => ({ name: t("rules.newName"), enabled: true, conditions: [emptyCondition()] as MailRule["conditions"], actions: { category: null, mark_read: false, skip_agent: false, notify: false, tag: null } });

function RuleEditor({ rule, onChange, onRemove }: { rule: MailRule; onChange: (rule: MailRule) => void; onRemove: () => void }) {
  const actions = rule.actions;
  const setCondition = (position: number, changes: Partial<RuleCondition>) => onChange({ ...rule, conditions: rule.conditions.map((item, i) => (i === position ? { ...item, ...changes } : item)) as MailRule["conditions"] });
  return (
    <fieldset data-testid="rule" aria-label={rule.name} className="flex flex-col gap-3 rounded-md border border-line-subtle p-4">
      <div className="flex items-end gap-3">
        <div className="min-w-0 flex-1"><Field label={t("rules.name")}>{({ invalid, ...control }) => <Input invalid={invalid} value={rule.name} onChange={(event) => onChange({ ...rule, name: event.target.value })} {...control} />}</Field></div>
        <IconButton icon="close" label={t("rules.remove", { name: rule.name })} onClick={onRemove} />
      </div>
      <Switch label={t("rules.enabled")} checked={rule.enabled ?? true} onChange={(enabled) => onChange({ ...rule, enabled })} />
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
    </fieldset>
  );
}

export function RulesSettings() {
  const toast = useToast();
  const saved = useRules();
  const save = useSaveRules();
  const [rules, setRules] = useState<MailRule[] | null>(null);
  useEffect(() => {
    if (saved.data && rules === null) setRules(saved.data.rules);
  }, [saved.data, rules]);
  return (
    <Card title={t("settings.section.rules")} description={t("rules.description")}>
      <div className="flex flex-col gap-4">
        {saved.isError ? <ErrorState title={t("rules.error")} onRetry={() => void saved.refetch()} /> : null}
        {rules === null && saved.isPending ? <Skeleton className="h-6 w-full" /> : null}
        {rules?.length === 0 ? <EmptyState icon="categories" title={t("rules.empty")} /> : null}
        {rules?.map((rule, index) => (
          <RuleEditor key={index} rule={rule} onChange={(next) => setRules(rules.map((item, i) => (i === index ? next : item)))} onRemove={() => setRules(rules.filter((_, i) => i !== index))} />
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
