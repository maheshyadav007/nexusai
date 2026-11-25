"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { MailCategory } from "@/ui/client/contracts.generated";
import { useCategories, useRules, useUpdateCategory } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { Field } from "@/ui/primitives/Field";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { t, tn } from "@/ui/strings";
import { ancestors, AUTOMATED, CALENDAR, categorySettingsHref, folderTree, keptFromAi, partlyKept } from "./customMail";

// Chips shown before the rest are left to the Sort page.
const SENDERS_SHOWN = 6;

/** One folder's name, what goes in it, and where it is, with the senders filed there. Moving
 *  it to the other home moves every sender in it, each keeping its one rule. */
export function EditFolder({ category, open, onOpenChange, onRenamed }: { category: MailCategory; open: boolean; onOpenChange: (open: boolean) => void; onRenamed: (name: string) => void }) {
  const client = useQueryClient();
  const update = useUpdateCategory();
  const rules = useRules();
  const categories = useCategories();
  const all = categories.data?.categories ?? [];
  const here = category.parent ? `folder:${category.parent}` : keptFromAi(category) ? "home:kept" : "home:reads";
  const [name, setName] = useState(category.name);
  const [description, setDescription] = useState(category.description ?? "");
  const [place, setPlace] = useState(here);
  useEffect(() => {
    if (!open) return;
    setName(category.name);
    setDescription(category.description ?? "");
    setPlace(here);
    update.reset();
  }, [open, category.name, here]);
  // Each sender a rule files here, and whether that rule keeps it from the AI.
  const senders = new Map<string, boolean>();
  for (const rule of rules.data?.rules ?? []) {
    if (rule.actions.category !== category.name) continue;
    for (const condition of rule.conditions) if ((condition.field === "sender" || condition.field === "sender_exact") && condition.value?.includes("@")) senders.set(condition.value.toLowerCase(), keptFromAi(category) || Boolean(rule.actions.skip_agent));
  }
  const list = [...senders.entries()];
  const whole = [AUTOMATED, CALENDAR].includes(category.name);
  // Not inside itself, nor inside anything under it.
  const inside = new Set([category.name, ...all.filter((item) => ancestors(all, item.name).includes(category.name)).map((item) => item.name)]);
  const options = [
    { value: "home:reads", label: t("nav.home.inbox") },
    ...folderTree(all, false).filter((row) => !inside.has(row.item.name)).map((row) => ({ value: `folder:${row.item.name}`, label: `${"\u2003".repeat(row.depth + 1)}${row.item.name}` })),
    { value: "home:kept", label: t("nav.home.kept") },
    ...folderTree(all, true).filter((row) => !inside.has(row.item.name)).map((row) => ({ value: `folder:${row.item.name}`, label: `${"\u2003".repeat(row.depth + 1)}${row.item.name}` })),
  ];
  const target = place.startsWith("folder:") ? all.find((item) => item.name === place.slice("folder:".length)) : undefined;
  const willKeep = place === "home:kept" || Boolean(target && keptFromAi(target));
  const save = () => {
    const clean = name.trim();
    const moved = place !== here;
    update.mutate(
      {
        name: category.name,
        ...(clean && clean !== category.name ? { new_name: clean } : {}),
        ...(description !== (category.description ?? "") ? { description } : {}),
        ...(moved ? { parent: target ? target.name : "", ai_reads: !willKeep } : {}),
      },
      { onSuccess: () => { void client.invalidateQueries({ queryKey: ["rules"] }); onOpenChange(false); if (clean && clean !== category.name) onRenamed(clean); } },
    );
  };
  return (
    <Dialog title={t("folder.edit.title")} open={open} onOpenChange={onOpenChange}>
      <form className="flex flex-col gap-4" onSubmit={(event) => { event.preventDefault(); if (name.trim() && !update.isPending) save(); }}>
        <Field label={t("categories.name")}>{({ invalid, ...control }) => <Input invalid={invalid} value={name} maxLength={64} onChange={(event) => setName(event.target.value)} {...control} />}</Field>
        <Field label={t("folder.edit.description")}>{({ invalid, ...control }) => <Textarea invalid={invalid} rows={2} value={description} maxLength={500} onChange={(event) => setDescription(event.target.value)} {...control} />}</Field>
        {whole ? <p className="text-sm text-ink-muted">{t("folder.edit.whole", { name: category.name })}</p> : (
          <div className="flex flex-col gap-2">
            <Field label={t("folder.edit.inside")} hint={t("folder.edit.inside.hint")}>
              {({ id, ...control }) => <Select id={id} {...(control["aria-describedby"] ? { describedBy: control["aria-describedby"] } : {})} value={place} options={options} onChange={setPlace} />}
            </Field>
            {partlyKept(category) && place === here ? <p className="text-sm text-ink-muted">{t("nav.folder.mixed")}</p> : null}
            {place !== here && willKeep !== keptFromAi(category) && list.length ? <p className="text-sm text-ink-secondary">{tn(willKeep ? "folder.edit.willKeep" : "folder.edit.willRead", list.length)}</p> : null}
          </div>
        )}
        {list.length ? (
          <div className="flex flex-col gap-2">
            <p className="text-sm text-ink-secondary">{tn("folder.edit.senders", list.length)}</p>
            <ul className="flex flex-wrap items-center gap-2">
              {list.slice(0, SENDERS_SHOWN).map(([sender, kept]) => <li key={sender} className="rounded-full border border-line-subtle px-2 py-px text-sm text-ink-secondary">{t(kept ? "folder.edit.sender.kept" : "folder.edit.sender.read", { sender })}</li>)}
              <li><Link href="/mail/sort" className="focus-ring rounded-sm text-sm text-accent-default hover:underline">{list.length > SENDERS_SHOWN ? t("folder.edit.more", { count: (list.length - SENDERS_SHOWN).toLocaleString() }) : t("folder.edit.openSort")}</Link></li>
            </ul>
          </div>
        ) : null}
        {update.isError ? <p role="alert" className="text-sm text-status-danger">{update.error.message}</p> : null}
        <div className="flex items-center justify-end gap-2">
          {/* The rule or AI description, and the rest, live on the folder's settings page. */}
          <Link href={categorySettingsHref(category.name)} onClick={() => onOpenChange(false)} className="focus-ring mr-auto rounded-sm text-sm text-accent-default hover:underline">{t("folder.edit.moreSettings")}</Link>
          <Button variant="quiet" onClick={() => onOpenChange(false)}>{t("folder.edit.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={!name.trim()} loading={update.isPending}>{t("settings.save")}</Button>
        </div>
      </form>
    </Dialog>
  );
}
