"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { MixedFolder } from "@/ui/client/contracts.generated";
import { useCategories, useMixedFolders, useSplitFolders } from "@/ui/client/mail";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { useToast } from "@/ui/primitives/Toast";
import { t, tn } from "@/ui/strings";

// Each half lists its biggest senders; the rest are in the folder all the same.
const SENDERS_SHOWN = 4;
const fmt = (n: number) => n.toLocaleString();
const keyOf = (name: string) => name.trim().replace(/\s+/g, " ").toLocaleLowerCase();

/** Shown once, at the top of the Sort page, for folders with senders on both sides: the half
 *  the AI reads keeps the name, and the kept half becomes a folder of its own in Kept from the
 *  AI, with a suggested name to change. Mail and rules move with each half. */
export function SplitReview() {
  const mixed = useMixedFolders();
  const categories = useCategories();
  const split = useSplitFolders();
  const client = useQueryClient();
  const toast = useToast();
  const [names, setNames] = useState<Readonly<Record<string, string>>>({});
  const [later, setLater] = useState(false);
  const rows = mixed.data?.folders ?? [];
  useEffect(() => setNames((current) => Object.fromEntries(rows.map((row) => [row.name, current[row.name] ?? row.suggested]))), [mixed.data]);
  if (later || !rows.length) return null;
  const taken = new Map((categories.data?.categories ?? []).filter((item) => !item.proposed).map((item) => [keyOf(item.name), item]));
  const chosen = rows.map((row) => keyOf(names[row.name] ?? row.suggested));
  const problem = (row: MixedFolder, index: number): string | null => {
    const name = (names[row.name] ?? row.suggested).trim();
    if (!name) return t("folder.new.nameNeeded");
    const clash = taken.get(keyOf(name));
    if (clash) return t("folder.new.taken", { name: clash.name, where: clash.parent ? t("folder.new.under", { name: clash.parent }) : t(clash.ai_reads === false ? "folder.new.inKept" : "folder.new.inInbox") });
    if (chosen.indexOf(keyOf(name)) !== index) return t("folder.new.taken", { name, where: t("folder.new.inKept") });
    return null;
  };
  const ready = rows.every((row, index) => !problem(row, index));
  // Sorting looks at the mail again, so the page shows each sender where it now is.
  const refresh = () => Promise.all(["mail-sort", "categories", "rules", "threads", "mixed-folders"].map((key) => client.invalidateQueries({ queryKey: [key] })));
  const splits = rows.map((row) => ({ name: row.name, kept_name: (names[row.name] ?? row.suggested).trim().replace(/\s+/g, " ") }));
  const run = () => split.mutate({ splits: splits as [typeof splits[number], ...typeof splits] }, {
    onSuccess: () => {
      void refresh();
      toast({
        title: tn("mail.sort.split.done", splits.length),
        action: { label: t("mail.sort.split.undo"), run: () => split.mutate({ splits: splits as [typeof splits[number], ...typeof splits], undo: true }, { onSuccess: () => void refresh() }) },
      });
    },
  });
  return (
    <section data-testid="sort-split" aria-label={tn("mail.sort.split.title", rows.length)} className="flex flex-col gap-5 rounded-lg border border-line-subtle bg-surface-sunken p-5">
      <div>
        <h2 className="text-lg font-medium text-ink-primary">{tn("mail.sort.split.title", rows.length)}</h2>
        <p className="text-md text-ink-secondary">{t("mail.sort.split.description")}</p>
      </div>
      {rows.map((row, index) => {
        const error = problem(row, index);
        return (
          <div key={row.name} data-testid="sort-split-folder" className="flex flex-col gap-2">
            <p className="flex items-center gap-2 text-md font-medium text-ink-primary"><Icon name="folder" className="h-4 w-4 text-accent-default" />{row.name}</p>
            <div className="grid gap-3 md:grid-cols-2">
              <Half icon="inbox" reads title={t("mail.sort.split.reads", { senders: tn("mail.sort.senderCount", row.read_senders.length), emails: fmt(row.read_emails) })} senders={row.read_senders}>
                <p className="py-2 text-md font-medium text-ink-primary">{row.name}</p>
                <p className="text-sm text-ink-muted">{t("mail.sort.split.keeps")}</p>
              </Half>
              <Half icon="keptFromAi" title={t("mail.sort.split.kept", { senders: tn("mail.sort.senderCount", row.kept_senders.length), emails: fmt(row.kept_emails) })} senders={row.kept_senders}>
                <Field label={t("mail.sort.split.name")} {...(error ? { error } : { hint: t("folder.new.free") })}>
                  {({ invalid, ...control }) => <Input invalid={invalid} value={names[row.name] ?? row.suggested} maxLength={64} onChange={(event) => setNames((current) => ({ ...current, [row.name]: event.target.value }))} {...control} />}
                </Field>
              </Half>
            </div>
          </div>
        );
      })}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line-subtle pt-4">
        <p className="text-sm text-ink-muted">{t("mail.sort.split.note")}</p>
        {split.isError ? <p role="alert" className="text-sm text-status-danger">{split.error.message}</p> : null}
        <div className="flex gap-2">
          <Button variant="quiet" onClick={() => setLater(true)}>{t("mail.sort.split.later")}</Button>
          <Button variant="primary" loading={split.isPending} disabled={!ready} onClick={run}>{tn("mail.sort.split.all", rows.length)}</Button>
        </div>
      </div>
    </section>
  );
}

function Half({ icon, reads = false, title, senders, children }: { icon: "inbox" | "keptFromAi"; reads?: boolean; title: string; senders: MixedFolder["read_senders"]; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-lg border border-line-subtle bg-surface-raised p-3">
      <p className="flex items-center gap-2 text-sm text-ink-muted"><Icon name={icon} className={`h-4 w-4 ${reads ? "text-accent-default" : "text-ink-faint"}`} />{title}</p>
      {children}
      <ul className="flex flex-col border-t border-line-subtle pt-2">
        {senders.slice(0, SENDERS_SHOWN).map((sender) => <li key={sender.sender} className="flex justify-between gap-3 py-px text-sm text-ink-secondary"><span className="min-w-0 truncate">{sender.sender}</span><span className="shrink-0 tabular-nums text-ink-muted">{fmt(sender.emails)}</span></li>)}
      </ul>
    </div>
  );
}
