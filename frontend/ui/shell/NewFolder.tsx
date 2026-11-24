"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { MailCategory, RuleCondition, SaveCategory } from "@/ui/client/contracts.generated";
import { useCategories, useRulePreview, useSaveCategory } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { Dialog } from "@/ui/primitives/Dialog";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Segmented } from "@/ui/primitives/Segmented";
import { Select } from "@/ui/primitives/Select";
import { useToast } from "@/ui/primitives/Toast";
import { t, tn, type StringKey } from "@/ui/strings";
import { categoryHref, folderTree, keptFromAi } from "./customMail";

/** Where a new folder goes: the top of a home, or inside a folder. */
export type Inside = "home:reads" | "home:kept" | `folder:${string}`;

const FIELDS: readonly { value: RuleCondition["field"]; label: StringKey }[] = [
  { value: "sender", label: "folder.new.field.sender" },
  { value: "subject", label: "folder.new.field.subject" },
  { value: "subject_prefix", label: "folder.new.field.subjectPrefix" },
  { value: "tag", label: "folder.new.field.tag" },
  { value: "header", label: "folder.new.field.header" },
  { value: "body", label: "folder.new.field.body" },
  { value: "has_attachment", label: "folder.new.field.attachment" },
];
// The names the homes and the Priority view have, which no folder can take.
const RESERVED = ["nav.home.inbox", "nav.home.kept", "nav.priority"] as const;
// How long typing settles before the matching mail is counted.
const COUNT_AFTER_MS = 400;
const blank = (field: RuleCondition["field"] = "body"): RuleCondition => ({ field, value: "" });

/** Whether a name is free anywhere in the tree, whatever its case, and if not, where it's used. */
export function clashOf(name: string, categories: readonly MailCategory[]): string | null {
  const clean = name.trim().replace(/\s+/g, " ").toLocaleLowerCase();
  if (!clean) return null;
  if (RESERVED.some((key) => t(key).toLocaleLowerCase() === clean)) return t("folder.new.reserved", { name: name.trim() });
  if (clean.includes("/")) return t("folder.new.slash");
  const taken = categories.find((item) => !item.proposed && item.name.toLocaleLowerCase() === clean);
  if (!taken) return null;
  const where = taken.parent ? t("folder.new.under", { name: taken.parent }) : t(keptFromAi(taken) ? "folder.new.inKept" : "folder.new.inInbox");
  return t("folder.new.taken", { name: taken.name, where });
}

/** Every place a folder can go: each home, then the folders in it, set in by depth. */
function places(categories: readonly MailCategory[]) {
  const nested = (kept: boolean) => folderTree(categories, kept).map((row) => ({ value: `folder:${row.item.name}`, label: `${" ".repeat(row.depth + 1)}${row.item.name}` }));
  return [{ value: "home:reads", label: t("nav.home.inbox") }, ...nested(false), { value: "home:kept", label: t("nav.home.kept") }, ...nested(true)];
}

/** One dialog for every new folder, on either side: its name, where it goes (which decides
 *  whether the AI reads it), and what fills it, a rule or the AI from a description. */
export function NewFolder({ open, onOpenChange, inside = "home:reads", onMade }: { open: boolean; onOpenChange: (open: boolean) => void; inside?: Inside; onMade?: (name: string) => void }) {
  const router = useRouter();
  const toast = useToast();
  const categories = useCategories();
  const save = useSaveCategory();
  const all = categories.data?.categories ?? [];
  const [name, setName] = useState("");
  const [place, setPlace] = useState<string>(inside);
  const [mode, setMode] = useState<"smart" | "exact">("exact");
  const [description, setDescription] = useState("");
  const [conditions, setConditions] = useState<RuleCondition[]>([blank(), blank("sender")]);
  const [priority, setPriority] = useState(true);
  const [existing, setExisting] = useState(true);
  const [counted, setCounted] = useState<RuleCondition[]>([]);
  useEffect(() => {
    if (!open) return;
    setName("");
    setPlace(inside);
    setDescription("");
    setConditions([blank(), blank("sender")]);
    setExisting(true);
    save.reset();
  }, [open, inside]);
  const parentName = place.startsWith("folder:") ? place.slice("folder:".length) : null;
  const parent = parentName ? all.find((item) => item.name === parentName) : undefined;
  const kept = place === "home:kept" || Boolean(parent && keptFromAi(parent));
  // Kept from the AI, the AI can't decide: it doesn't read that mail.
  const chosen = kept ? "exact" : mode;
  useEffect(() => setPriority(!kept), [kept]);
  useEffect(() => {
    const timer = window.setTimeout(() => setCounted(conditions), COUNT_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, [conditions]);
  const preview = useRulePreview(chosen === "exact" ? counted : []);
  const clash = clashOf(name, all);
  const usable = conditions.filter((condition) => condition.field === "has_attachment" || (condition.value ?? "").trim());
  const failed = save.error instanceof ApiRequestError ? save.error.detail.message : save.error?.message;
  const ready = Boolean(name.trim()) && !clash && (chosen === "smart" ? Boolean(description.trim()) : usable.length > 0);
  const change = (index: number, next: Partial<RuleCondition>) => setConditions((list) => list.map((item, at) => (at === index ? { ...item, ...next } : item)));
  const submit = () => {
    const clean = name.trim().replace(/\s+/g, " ");
    const input: SaveCategory = {
      name: clean,
      parent: parentName,
      ai_reads: !kept,
      mode: chosen,
      description: chosen === "smart" ? description.trim() : "",
      conditions: (chosen === "exact" ? usable : []) as SaveCategory["conditions"],
      in_priority: priority,
      file_existing: chosen === "exact" && existing,
    };
    save.mutate(input, {
      onSuccess: (result) => {
        onOpenChange(false);
        toast({ title: result.filed ? tn("folder.new.made.filed", result.filed, { name: clean }) : t("folder.new.made", { name: clean }) });
        if (onMade) onMade(clean);
        else router.push(categoryHref(clean));
      },
    });
  };
  return (
    <Dialog title={t("folder.new.title")} description={t("folder.new.description")} open={open} onOpenChange={onOpenChange}>
      <form className="flex flex-col gap-4" onSubmit={(event) => { event.preventDefault(); if (ready && !save.isPending) submit(); }}>
        <Field label={t("categories.name")} {...(clash ? { error: clash } : name.trim() ? { hint: t("folder.new.free") } : {})}>
          {({ invalid, ...control }) => <Input invalid={invalid} value={name} maxLength={64} onChange={(event) => setName(event.target.value)} {...control} />}
        </Field>
        <Field label={t("folder.new.inside")} hint={t("folder.new.inside.hint")}>
          {({ id, ...control }) => <Select id={id} {...(control["aria-describedby"] ? { describedBy: control["aria-describedby"] } : {})} value={place} options={places(all)} onChange={setPlace} />}
        </Field>
        <div className="flex flex-col gap-2">
          <Segmented label={t("folder.new.what")} value={chosen} options={[{ value: "smart", label: t("folder.new.ai"), disabled: kept }, { value: "exact", label: t("folder.new.rule") }]} onChange={setMode} />
          {kept ? <p className="text-sm text-ink-muted">{t("folder.new.keptRule")}</p> : null}
          {chosen === "smart" ? (
            <Field label={t("folder.new.describe")} hint={t("folder.new.describe.hint")}>
              {({ invalid, ...control }) => <Textarea invalid={invalid} rows={2} value={description} maxLength={500} onChange={(event) => setDescription(event.target.value)} {...control} />}
            </Field>
          ) : (
            <div className="flex flex-col gap-2">
              <ul className="flex flex-col gap-2">
                {conditions.map((condition, index) => (
                  <li key={index} className="flex items-center gap-2">
                    <span className="w-thumb shrink-0">
                      <Select label={t("folder.new.field")} value={condition.field} options={FIELDS.map((field) => ({ value: field.value, label: t(field.label) }))} onChange={(field) => change(index, { field: field as RuleCondition["field"] })} />
                    </span>
                    {condition.field === "header" ? <Input aria-label={t("folder.new.headerName")} placeholder={t("folder.new.headerName")} value={condition.header ?? ""} maxLength={100} onChange={(event) => change(index, { header: event.target.value })} className="min-w-0 flex-1" /> : null}
                    {condition.field === "has_attachment" ? <span className="min-w-0 flex-1" /> : <Input aria-label={t("folder.new.value", { field: t((FIELDS.find((field) => field.value === condition.field) ?? FIELDS[0]!).label) })} placeholder={t(condition.field === "sender" ? "folder.new.placeholder.sender" : "folder.new.placeholder.text")} value={condition.value} maxLength={500} onChange={(event) => change(index, { value: event.target.value })} className="min-w-0 flex-1" />}
                    {conditions.length > 1 ? <IconButton icon="close" label={t("folder.new.removeCondition")} onClick={() => setConditions((list) => list.filter((_, at) => at !== index))} /> : null}
                  </li>
                ))}
              </ul>
              {conditions.length < 10 ? <Button variant="quiet" className="self-start py-px" onClick={() => setConditions((list) => [...list, blank("subject")])}>{t("folder.new.addCondition")}</Button> : null}
              <p className="text-sm text-ink-muted">{t("folder.new.allMatch")}</p>
            </div>
          )}
        </div>
        <Checkbox label={t("categories.priority")} checked={priority} onChange={setPriority} />
        {chosen === "exact" ? (
          <div className="flex flex-col gap-1">
            <Checkbox label={t("folder.new.existing")} checked={existing} onChange={setExisting} />
            <p role="status" className="pl-6 text-sm tabular-nums text-ink-muted">
              {!usable.length ? t("folder.new.count.waiting") : preview.isFetching || !preview.data ? t("folder.new.count.counting") : tn("folder.new.count", preview.data.conversations)}
            </p>
          </div>
        ) : null}
        {failed ? <p role="alert" className="text-sm text-status-danger">{failed}</p> : null}
        <div className="flex justify-end">
          <Button type="submit" variant="primary" loading={save.isPending} disabled={!ready}>{t("categories.create")}</Button>
        </div>
      </form>
    </Dialog>
  );
}
