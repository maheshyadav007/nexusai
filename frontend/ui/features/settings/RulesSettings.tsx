"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { MailRule, RuleCondition } from "@/ui/client/contracts.generated";
import { useCategories, useRules, useSaveRules, useWholeRulePreview } from "@/ui/client/mail";
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
import { TextLink } from "@/ui/primitives/TextLink";
import { useToast } from "@/ui/primitives/Toast";
import { t, tn } from "@/ui/strings";

const FIELDS = [
  { value: "subject", label: t("rules.field.subject") },
  { value: "subject_prefix", label: t("rules.field.subjectPrefix") },
  { value: "subject_words", label: t("rules.field.subjectWords") },
  { value: "tag", label: t("rules.field.tag") },
  { value: "sender", label: t("rules.field.sender") },
  { value: "sender_exact", label: t("rules.field.senderExact") },
  { value: "to", label: t("rules.field.to") },
  { value: "body", label: t("rules.field.body") },
  { value: "header", label: t("rules.field.header") },
  { value: "has_attachment", label: t("rules.field.attachment") },
];

type Field = RuleCondition["field"];
// What a condition looks at, then how: "From · is", "Subject · has the tag". The second list only
// offers what fits the first, so no wrong pair can be built.
const PARTS: readonly { value: string; label: string; ways: readonly { value: Field; label: string }[] }[] = [
  { value: "from", label: t("rules.part.from"), ways: [{ value: "sender_exact", label: t("rules.way.is") }, { value: "sender", label: t("rules.way.has") }] },
  {
    value: "subject",
    label: t("rules.part.subject"),
    ways: [
      { value: "subject_words", label: t("rules.way.words") },
      { value: "subject", label: t("rules.way.has") },
      { value: "subject_prefix", label: t("rules.way.startsWith") },
      { value: "tag", label: t("rules.way.tag") },
    ],
  },
  { value: "body", label: t("rules.part.body"), ways: [{ value: "body", label: t("rules.way.has") }] },
  { value: "to", label: t("rules.part.to"), ways: [{ value: "to", label: t("rules.way.has") }] },
  { value: "attachment", label: t("rules.part.attachment"), ways: [{ value: "has_attachment", label: t("rules.way.any") }] },
  { value: "header", label: t("rules.part.header"), ways: [{ value: "header", label: t("rules.way.has") }] },
];
const partOf = (field: Field) => PARTS.find((part) => part.ways.some((way) => way.value === field)) ?? (PARTS[0] as (typeof PARTS)[number]);

const emptyCondition = (): RuleCondition => ({ field: "subject_words", value: "" });
const emptyRule = (): MailRule => ({ name: t("rules.newName"), enabled: true, match: "all", conditions: [emptyCondition()] as MailRule["conditions"], exceptions: [], actions: { category: null, mark_read: false, skip_agent: false, notify: false, tag: null } });
const filled = (condition: RuleCondition) => condition.field === "has_attachment" || Boolean((condition.value ?? "").trim());

/** One condition in words, the way a person would say it. */
export function phrase(condition: RuleCondition): string {
  const value = condition.value ?? "";
  switch (condition.field) {
    case "sender_exact": return t("rules.said.from", { sender: value });
    case "tag": return t("rules.said.tag", { tag: value });
    case "subject_prefix": return t("rules.said.startsWith", { value });
    case "subject": return t("rules.said.has", { value });
    case "subject_words": return t("rules.said.words", { value });
    case "to": return t("rules.said.to", { value });
    case "has_attachment": return t("rules.field.attachment");
    case "header": return t("rules.said.header", { header: condition.header ?? "", value });
    default: return t("rules.matches", { field: FIELDS.find((item) => item.value === condition.field)?.label ?? condition.field, value });
  }
}

/** A whole rule in words: every condition it needs, joined by and or or, then what it leaves alone. */
export function phraseRule(rule: MailRule): string {
  const joined = rule.conditions.filter(filled).map(phrase).join(t(rule.match === "any" ? "rules.said.or" : "rules.said.and"));
  const except = (rule.exceptions ?? []).filter(filled).map(phrase).join(t("rules.said.or"));
  return except ? t("rules.said.except", { rule: joined, except }) : joined;
}

/** The rule said back as one sentence, so what it does is never a guess: "Mail where from x or
 * subject has the tag [PLM] goes to PLM, except when subject has the words “escalated”. The AI
 * doesn't read it." */
function RuleSentence({ rule }: { rule: MailRule }) {
  const lower = (text: string) => text.charAt(0).toLocaleLowerCase() + text.slice(1);
  const what = rule.conditions.filter(filled).map((c) => lower(phrase(c))).join(t(rule.match === "any" ? "rules.said.or" : "rules.said.and"));
  const except = (rule.exceptions ?? []).filter(filled).map((c) => lower(phrase(c))).join(t("rules.said.or"));
  const where = rule.actions.category;
  return (
    <p data-testid="rule-sentence" className="rounded-md bg-surface-sunken px-3 py-2 text-md text-ink-primary">
      {what
        ? [
            t("rules.sentence.mail", { what }),
            where ? t("rules.sentence.goes", { folder: where }) : "",
            except ? t("rules.sentence.except", { except }) : "",
            ". ",
            t(rule.actions.skip_agent ? "rules.sentence.hidden" : "rules.sentence.reads"),
          ].join("")
        : t("rules.sentence.empty")}
    </p>
  );
}

function ConditionRow({ condition, label, onChange, onRemove }: { condition: RuleCondition; label: string; onChange: (changes: Partial<RuleCondition>) => void; onRemove: () => void }) {
  const part = partOf(condition.field);
  return (
    <div data-testid="rule-condition" className="flex flex-wrap items-center gap-2">
      <div className="w-36"><Select label={t("rules.part")} value={part.value} options={PARTS} compact onChange={(value) => onChange({ field: (PARTS.find((item) => item.value === value) ?? part).ways[0]?.value ?? "subject" })} /></div>
      {part.ways.length > 1 ? <div className="w-40"><Select label={t("rules.way")} value={condition.field} options={part.ways} compact onChange={(field) => onChange({ field: field as Field })} /></div> : <span className="text-sm text-ink-muted">{part.ways[0]?.label}</span>}
      {condition.field === "header" ? <div className="w-32"><Input aria-label={t("rules.header")} placeholder={t("rules.header")} value={condition.header ?? ""} onChange={(event) => onChange({ header: event.target.value })} /></div> : null}
      {condition.field === "has_attachment" ? <span className="flex-1" /> : <div className="min-w-40 flex-1"><Input aria-label={label} value={condition.value ?? ""} onChange={(event) => onChange({ value: event.target.value })} /></div>}
      <IconButton icon="close" label={t("rules.removeCondition")} onClick={onRemove} />
    </div>
  );
}

function Conditions({ items, label, add, onChange }: { items: readonly RuleCondition[]; label: string; add: string; onChange: (items: RuleCondition[]) => void }) {
  return (
    <div className="flex flex-col gap-2">
      {items.map((condition, position) => (
        <ConditionRow key={position} condition={condition} label={label} onChange={(changes) => onChange(items.map((item, i) => (i === position ? { ...item, ...changes } : item)))} onRemove={() => onChange(items.filter((_, i) => i !== position))} />
      ))}
      <div><Button variant="quiet" onClick={() => onChange([...items, emptyCondition()])}>{add}</Button></div>
    </div>
  );
}

/** What the rule as written catches among the mail already here, and which of it still reaches the AI. */
function RuleCatches({ rule }: { rule: MailRule }) {
  const [settled, setSettled] = useState<MailRule | null>(null);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(rule.conditions.some(filled) ? rule : null), 400);
    return () => clearTimeout(timer);
  }, [rule]);
  const preview = useWholeRulePreview(settled);
  if (!settled || !preview.data) return null;
  const { conversations, named, examples } = preview.data;
  return (
    <div data-testid="rule-catches" className="flex flex-col gap-1 border-t border-line-subtle pt-3">
      <p className="text-sm text-ink-secondary">
        <span className="font-medium text-ink-primary">{tn("rules.catches", conversations)}</span>
        {rule.actions.skip_agent && named ? ` · ${tn("rules.catches.named", named)}` : ""}
      </p>
      {examples.map((example) => (
        <div key={example.thread} className="flex justify-between gap-4 border-t border-line-subtle py-1 text-sm first:border-t-0">
          <span className="min-w-0 truncate text-ink-primary">{example.subject}{example.named ? <span className="text-ink-muted"> — {example.named}</span> : null}</span>
          <span className={`shrink-0 ${example.named ? "text-accent-default" : "text-ink-muted"}`}>{example.named ? t("rules.catches.reaches") : example.sender}</span>
        </div>
      ))}
    </div>
  );
}

function RuleEditor({ rule, onChange, onRemove, startsOpen }: { rule: MailRule; onChange: (rule: MailRule) => void; onRemove: () => void; startsOpen: boolean }) {
  const actions = rule.actions;
  const folders = useCategories().data?.categories ?? [];
  const suggestions = useId();
  // A folder that exists brings its side with it; a new name keeps what's ticked below.
  const setFolder = (name: string) => {
    const folder = folders.find((item) => item.name === name);
    onChange({ ...rule, actions: { ...actions, category: name || null, skip_agent: folder ? folder.ai_reads === false : actions.skip_agent } });
  };
  return (
    <ExpandRow
      testid="rule"
      label={t("rules.open", { name: rule.name })}
      defaultOpen={startsOpen}
      title={rule.name}
      meta={
        <>
          {t(rule.enabled === false ? "rules.off" : "rules.on")}
          {rule.conditions.some(filled) ? ` · ${phraseRule(rule)}` : ""}
          {actions.category ? ` · ${t("rules.filesInto", { category: actions.category })}` : ""}
        </>
      }
      aside={<Switch label={t("rules.enabled")} hideLabel checked={rule.enabled ?? true} onChange={(enabled) => onChange({ ...rule, enabled })} />}
    >
      <div className="flex items-end gap-3">
        <div className="min-w-0 flex-1"><Field label={t("rules.name")}>{({ invalid, ...control }) => <Input invalid={invalid} value={rule.name} onChange={(event) => onChange({ ...rule, name: event.target.value })} {...control} />}</Field></div>
        <IconButton icon="close" label={t("rules.remove", { name: rule.name })} onClick={onRemove} />
      </div>
      <RuleSentence rule={rule} />
      <div className="flex flex-wrap items-center gap-2 text-md font-medium text-ink-primary">
        <span>{t("rules.when.lead")}</span>
        <div className="w-24"><Select label={t("rules.match")} value={rule.match ?? "all"} options={[{ value: "all", label: t("rules.match.all") }, { value: "any", label: t("rules.match.any") }]} compact onChange={(match) => onChange({ ...rule, match: match as MailRule["match"] })} /></div>
        <span>{t("rules.when.tail")}</span>
      </div>
      <Conditions items={rule.conditions} label={t("rules.contains")} add={t("rules.addCondition")} onChange={(conditions) => onChange({ ...rule, conditions: (conditions.length ? conditions : [emptyCondition()]) as MailRule["conditions"] })} />
      <p className="text-md font-medium text-ink-primary">{t("rules.except")}</p>
      <Conditions items={rule.exceptions ?? []} label={t("rules.contains")} add={t("rules.addException")} onChange={(exceptions) => onChange({ ...rule, exceptions: exceptions as MailRule["exceptions"] })} />
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-md font-medium text-ink-primary">{t("rules.then.put")}</span>
        <div className="w-60">
          <Input aria-label={t("rules.category")} list={suggestions} placeholder={t("rules.noFolder")} value={actions.category ?? ""} onChange={(event) => setFolder(event.target.value)} />
          <datalist id={suggestions}>{folders.map((folder) => <option key={folder.name} value={folder.name} />)}</datalist>
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <Checkbox label={t("rules.markRead")} checked={actions.mark_read ?? false} onChange={(mark_read) => onChange({ ...rule, actions: { ...actions, mark_read } })} />
        <Checkbox label={t("rules.skipAgent")} checked={actions.skip_agent ?? false} onChange={(skip_agent) => onChange({ ...rule, actions: { ...actions, skip_agent } })} />
        <Checkbox label={t("rules.notify")} checked={actions.notify ?? false} onChange={(notify) => onChange({ ...rule, actions: { ...actions, notify } })} />
      </div>
      {actions.skip_agent ? <p className="text-sm text-ink-muted">{t("rules.namedStill")} <TextLink href="/settings?section=me">{t("me.title")}</TextLink></p> : null}
      <RuleCatches rule={rule} />
    </ExpandRow>
  );
}

// What the Sort step and "Move to Inbox" write. They show by folder, in words, not one row each.
const SORTED = "Sorted: ";
const READS = "AI reads: ";
const written = (rule: MailRule) => rule.name.startsWith(SORTED) || rule.name.startsWith(READS);

/** One rule the app wrote, as a sentence: what it matches. */
function said(rule: MailRule): string {
  return phraseRule(rule);
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
