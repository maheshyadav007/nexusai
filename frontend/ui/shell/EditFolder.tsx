"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { MailCategory } from "@/ui/client/contracts.generated";
import { useRules, useUpdateCategory } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { Field } from "@/ui/primitives/Field";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Segmented } from "@/ui/primitives/Segmented";
import { t, tn } from "@/ui/strings";
import { AUTOMATED, CALENDAR, keptFromAi } from "./customMail";

// Chips shown before the rest are left to the Sort page.
const SENDERS_SHOWN = 6;
type Side = "reads" | "ignores";

/** One folder's name, what goes in it, and whether the AI reads it, with the senders filed
 *  there. Choosing a side moves every one of them, each keeping its one rule. */
export function EditFolder({ category, open, onOpenChange, onRenamed }: { category: MailCategory; open: boolean; onOpenChange: (open: boolean) => void; onRenamed: (name: string) => void }) {
  const client = useQueryClient();
  const update = useUpdateCategory();
  const rules = useRules();
  const [name, setName] = useState(category.name);
  const [description, setDescription] = useState(category.description ?? "");
  const [side, setSide] = useState<Side | undefined>(undefined);
  useEffect(() => {
    if (!open) return;
    setName(category.name);
    setDescription(category.description ?? "");
    setSide(undefined);
    update.reset();
  }, [open, category.name]);
  // Each sender a rule files here, and whether that rule keeps it from the AI.
  const senders = new Map<string, boolean>();
  for (const rule of rules.data?.rules ?? []) {
    if (rule.actions.category !== category.name) continue;
    for (const condition of rule.conditions) if ((condition.field === "sender" || condition.field === "sender_exact") && condition.value?.includes("@")) senders.set(condition.value.toLowerCase(), Boolean(rule.actions.skip_agent));
  }
  const list = [...senders.entries()];
  const read = list.filter(([, kept]) => !kept).length;
  const mixed = list.length > 0 && read > 0 && read < list.length;
  const now: Side | undefined = mixed ? undefined : keptFromAi(category) ? "ignores" : "reads";
  const whole = [AUTOMATED, CALENDAR].find((top) => category.name === top || category.name.startsWith(`${top}/`));
  const chosen = side ?? now;
  const save = () => {
    const clean = name.trim();
    update.mutate(
      { name: category.name, ...(clean && clean !== category.name ? { new_name: clean } : {}), ...(description !== (category.description ?? "") ? { description } : {}), ...(side && side !== now ? { ai_reads: side === "reads" } : {}) },
      { onSuccess: () => { void client.invalidateQueries({ queryKey: ["rules"] }); onOpenChange(false); if (clean && clean !== category.name) onRenamed(clean); } },
    );
  };
  return (
    <Dialog title={t("folder.edit.title")} open={open} onOpenChange={onOpenChange}>
      <form className="flex flex-col gap-4" onSubmit={(event) => { event.preventDefault(); if (name.trim() && !update.isPending) save(); }}>
        <Field label={t("categories.name")}>{({ invalid, ...control }) => <Input invalid={invalid} value={name} maxLength={64} onChange={(event) => setName(event.target.value)} {...control} />}</Field>
        <Field label={t("folder.edit.description")}>{({ invalid, ...control }) => <Textarea invalid={invalid} rows={2} value={description} maxLength={500} onChange={(event) => setDescription(event.target.value)} {...control} />}</Field>
        <div className="flex flex-col gap-2">
          {whole ? <p className="text-sm text-ink-muted">{t("folder.edit.whole", { name: whole })}</p> : (
            <>
              <Segmented label={t("folder.edit.reads")} value={chosen} options={[{ value: "reads", label: t("mail.sort.side.reads") }, { value: "ignores", label: t("mail.sort.side.ignores") }]} onChange={setSide} />
              {mixed && !side ? <p className="text-sm text-ink-muted">{t("folder.edit.mixed", { read: read.toLocaleString(), count: list.length.toLocaleString() })}</p> : null}
              {side && side !== now && list.length ? <p className="text-sm text-ink-secondary">{tn(side === "reads" ? "folder.edit.willRead" : "folder.edit.willKeep", list.length)}</p> : null}
            </>
          )}
        </div>
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
        <div className="flex justify-end gap-2">
          <Button variant="quiet" onClick={() => onOpenChange(false)}>{t("folder.edit.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={!name.trim()} loading={update.isPending}>{t("settings.save")}</Button>
        </div>
      </form>
    </Dialog>
  );
}
