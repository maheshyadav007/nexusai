"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useSearch } from "@/ui/client/mail";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";
import { ThreadRowView } from "./ThreadRowView";

export function SearchScreen() {
  const query = useSearchParams().get("q") ?? "";
  const [text, setText] = useState(query);
  const [sender, setSender] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [attachments, setAttachments] = useState(false);
  const active = Boolean(text.trim() || sender.trim());
  const search = useSearch(
    {
      query: text,
      ...(sender ? { sender } : {}),
      ...(from ? { date_from: from } : {}),
      ...(to ? { date_to: `${to}T23:59:59` } : {}),
      ...(attachments ? { has_attachment: true } : {}),
    },
    active,
  );
  const hits = search.data?.hits ?? [];
  return (
    <div className="mx-auto flex max-w-content flex-col gap-4 p-6">
      <h1 className="font-serif text-display text-ink-primary">{t("search.title")}</h1>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label={t("search.words")}>{({ invalid, ...control }) => <Input invalid={invalid} value={text} onChange={(event) => setText(event.target.value)} {...control} />}</Field>
        <Field label={t("search.sender")}>{({ invalid, ...control }) => <Input invalid={invalid} value={sender} onChange={(event) => setSender(event.target.value)} {...control} />}</Field>
        <Field label={t("search.from")}>{({ invalid, ...control }) => <Input type="date" invalid={invalid} value={from} onChange={(event) => setFrom(event.target.value)} {...control} />}</Field>
        <Field label={t("search.until")}>{({ invalid, ...control }) => <Input type="date" invalid={invalid} value={to} onChange={(event) => setTo(event.target.value)} {...control} />}</Field>
      </div>
      <Checkbox label={t("search.attachments")} checked={attachments} onChange={setAttachments} />
      {!active ? <EmptyState icon="search" title={t("search.prompt")} /> : null}
      {active && search.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {search.isError ? <ErrorState title={t("search.error")} onRetry={() => void search.refetch()} /> : null}
      {active && search.isSuccess && hits.length === 0 ? <EmptyState icon="search" title={t("search.none")} /> : null}
      <ul aria-label={t("search.results")} className="flex flex-col gap-1">
        {hits.map((hit) => (
          <li key={hit.thread.id} data-testid="search-hit">
            <ThreadRowView thread={hit.thread} excerpt={hit.excerpt} />
          </li>
        ))}
      </ul>
    </div>
  );
}
