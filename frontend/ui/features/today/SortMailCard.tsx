"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { query } from "@/ui/client/api";
import { useHomeReady, useLeadName } from "@/ui/client/home";
import { Card } from "@/ui/primitives/Card";
import { t } from "@/ui/strings";

/** Shown while a new mailbox waits to be sorted, since the AI reads nothing until it is. */
export function SortMailCard() {
  const ready = useHomeReady();
  const lead = useLeadName();
  // Kept current by events (mail.sortChanged), so nothing here asks again on a timer.
  const sort = useQuery({ queryKey: ["mail-sort"], queryFn: () => query("mail.sort.get", {}), enabled: ready });
  const data = sort.data;
  if (!data || (data.state !== "ready" && data.state !== "preparing")) return null;
  // The same figure the sorting page starts with: what it would keep from the AI.
  const automated = (data.senders ?? []).filter((sender) => sender.side === "ignores").reduce((n, sender) => n + sender.count, 0) + (data.calendar ?? 0);
  return <Card title={t("mail.sort.card.title")}>
    <div className="flex flex-col gap-3">
      <p className="text-md text-ink-secondary">{data.state !== "ready" ? t("mail.sort.card.preparing", { name: lead }) : automated ? t("mail.sort.card.ready", { name: lead, count: automated.toLocaleString() }) : t("mail.sort.card.none", { name: lead })}</p>
      <div><Link href="/mail/sort" className="focus-ring press inline-flex items-center justify-center gap-2 rounded-md bg-accent-default px-3 py-2 text-md font-medium text-accent-on hover:bg-accent-hover">{t("mail.sort.card.open")}</Link></div>
    </div>
  </Card>;
}
