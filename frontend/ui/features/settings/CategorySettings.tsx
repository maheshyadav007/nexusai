"use client";

import { useSearchParams } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiRequestError, command } from "@/ui/client/api";
import type { MailCategory } from "@/ui/client/contracts.generated";
import { useRelativeTime } from "@/ui/client/format";
import { useCategories, useRemoveCategory, useReorderCategories, useUpdateCategory } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Sortable } from "@/ui/primitives/Sortable";
import { Switch } from "@/ui/primitives/Switch";
import { t, tn } from "@/ui/strings";

const SOURCE = { user: "categories.source.user", agent: "categories.source.agent", rule: "categories.source.rule" } as const;

function CategoryRow({ item }: { item: MailCategory }) {
  const selected = useSearchParams().get("category") === item.name;
  const update = useUpdateCategory();
  const remove = useRemoveCategory();
  const sort = useMutation({ mutationFn: (confirm: boolean) => command("categories.sort", { name: item.name, confirm }) });
  const relative = useRelativeTime();
  const [name, setName] = useState(item.name);
  const [mode, setMode] = useState<"exact" | "smart">(item.mode ?? "smart");
  useEffect(() => setMode(item.mode ?? "smart"), [item.mode]);
  const [sender, setSender] = useState(item.sender ?? "");
  const [description, setDescription] = useState(item.description ?? item.name);
  useEffect(() => setDescription(item.description ?? item.name), [item.description, item.name]);
  const [subject, setSubject] = useState(item.subject ?? "");
  useEffect(() => setName(item.name), [item.name]);
  useEffect(() => { if (selected) document.getElementById(`category-${item.name}`)?.scrollIntoView({ block: "center" }); }, [selected, item.name]);
  useEffect(() => setSender(item.sender ?? ""), [item.sender]);
  useEffect(() => setSubject(item.subject ?? ""), [item.subject]);
  const refused = update.error instanceof ApiRequestError ? update.error.detail.message : null;
  const rule = item.sender || item.subject;
  return (
    <div id={`category-${item.name}`}><ExpandRow
      defaultOpen={selected}
      testid="category"
      label={t("categories.open", { name: item.name })}
      title={item.name}
      meta={
        <>
          {tn("categories.count", item.count ?? 0)}
          {item.in_priority ? ` · ${t("categories.inPriority")}` : ""}
          {rule ? ` · ${t("categories.from", { sender: rule })}` : ""}
        </>
      }
    >
      <Field label={t("categories.name")} {...(refused ? { error: refused } : {})}>
        {({ invalid, ...control }) => <Input invalid={invalid} value={name} onChange={(event) => setName(event.target.value)} onBlur={() => name.trim() && name !== item.name && update.mutate({ name: item.name, new_name: name.trim() }, { onError: () => setName(item.name) })} {...control} />}
      </Field>
      <Select label={t("categories.mode")} value={mode} options={[{ value: "exact", label: t("categories.mode.exact") }, { value: "smart", label: t("categories.mode.smart") }]} onChange={(value) => { setMode(value as "exact" | "smart"); update.mutate({ name: item.name, mode: value as "exact" | "smart" }); }} />
      <p className="text-sm text-ink-muted">{t("categories.switchHint")}</p>
      {mode === "smart" ? <Field label={t("categories.smartDescription")}>{({ invalid, ...control }) => <Input invalid={invalid} value={description} maxLength={500} onChange={(event) => setDescription(event.target.value)} onBlur={() => description !== item.description && update.mutate({ name: item.name, description })} {...control} />}</Field> : null}
      {mode === "exact" ? <div className="grid gap-3 md:grid-cols-2">
        <Field label={t("categories.sender")}>{({ invalid, ...control }) => <Input invalid={invalid} spellCheck={false} value={sender} onChange={(event) => setSender(event.target.value)} onBlur={() => sender !== (item.sender ?? "") && update.mutate(sender.trim() || subject.trim() ? { name: item.name, sender: sender.trim() || null, subject: subject.trim() || null } : { name: item.name, clear_rule: true })} {...control} />}</Field>
        <Field label={t("categories.subject")}>{({ invalid, ...control }) => <Input invalid={invalid} spellCheck={false} value={subject} onChange={(event) => setSubject(event.target.value)} onBlur={() => subject !== (item.subject ?? "") && update.mutate(sender.trim() || subject.trim() ? { name: item.name, sender: sender.trim() || null, subject: subject.trim() || null } : { name: item.name, clear_rule: true })} {...control} />}</Field>
      </div> : null}
      <Button loading={sort.isPending} onClick={() => sort.mutate(false)}>{t("categories.sort")}</Button>
      {sort.data && !sort.data.queued ? <div className="flex items-center gap-3"><p>{t("categories.sort.cost", { count: sort.data.conversations, tokens: sort.data.estimated_tokens })}</p><Button loading={sort.isPending} onClick={() => sort.mutate(true)}>{t("categories.sort.confirm")}</Button></div> : null}
      {sort.error ? <ErrorState title={sort.error.message} /> : null}
      <Switch label={t("categories.priority")} checked={item.in_priority} onChange={(in_priority) => update.mutate({ name: item.name, in_priority })} />
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm tabular-nums text-ink-muted">
          {t(SOURCE[item.source])}
          {item.updated ? ` · ${t("tasks.changed", { when: relative(item.updated) })}` : ""}
        </p>
        <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate(item.name)}>
          {t("categories.remove")}
        </Button>
      </div>
    </ExpandRow></div>
  );
}

export function CategorySettings() {
  const selected = useSearchParams().get("category");
  const categories = useCategories();
  const reorder = useReorderCategories();
  const rows = (categories.data?.categories ?? []).filter((item) => !item.proposed);
  return (
    <Card title={t("nav.categories")} description={t("categories.description")}>
      {categories.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {categories.isError ? <ErrorState title={t("categories.error")} onRetry={() => void categories.refetch()} /> : null}
      {categories.isSuccess && rows.length === 0 ? <EmptyState icon="categories" title={t("categories.empty")} /> : null}
      {rows.length ? <Sortable label={t("nav.categories")} items={rows.map((item) => ({ id: item.name, label: item.name, content: <CategoryRow key={`${item.name}-${selected}`} item={item} /> }))} onReorder={(names) => reorder.mutate(names)} /> : null}
    </Card>
  );
}
