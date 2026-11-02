"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useDocuments } from "@/ui/client/documents";
import { useCategories, useMailFolders, useSearch } from "@/ui/client/mail";
import { useDocumentActions, usePreview } from "@/ui/features/documents/DocumentPreview";
import { sizeOf } from "@/ui/features/documents/sizes";
import { ThreadRowView } from "@/ui/features/mail/ThreadRowView";
import { MeaningNotice } from "@/ui/features/settings/LocalModelSettings";
import { Icon } from "@/ui/icons";
import { Badge } from "@/ui/primitives/Badge";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Input } from "@/ui/primitives/Input";
import { Pressable } from "@/ui/primitives/Pressable";
import { Segmented } from "@/ui/primitives/Segmented";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";
import type { DocumentRow } from "@/ui/client/contracts.generated";
import { datesOf, Highlight, parseQuery, SearchFilters, type Chosen, type FilterOption } from "./SearchFilters";

type Tab = "mail" | "documents";
type FileType = "pdf" | "word" | "sheet" | "slides" | "image" | "other";

const FILE_TYPES: readonly { value: FileType; label: "search.type.pdf" | "search.type.word" | "search.type.sheet" | "search.type.slides" | "search.type.image" | "search.type.other" }[] = [
  { value: "pdf", label: "search.type.pdf" },
  { value: "word", label: "search.type.word" },
  { value: "sheet", label: "search.type.sheet" },
  { value: "slides", label: "search.type.slides" },
  { value: "image", label: "search.type.image" },
  { value: "other", label: "search.type.other" },
];
const SPECIAL_ROLES: Readonly<Record<string, "nav.inbox" | "nav.sent" | "nav.drafts" | "nav.archive">> = { inbox: "nav.inbox", sent: "nav.sent", drafts: "nav.drafts", archive: "nav.archive" };
const HIDDEN_FOLDERS = new Set(["all", "trash", "junk"]);
const DOCUMENT_LIMIT = 200;

function MailResults({ text, chosen, onChange }: { text: string; chosen: Chosen; onChange: (next: Chosen) => void }) {
  const folders = useMailFolders();
  const categories = useCategories();
  const { words, sender } = parseQuery(text);
  const who = sender ?? chosen.sender;
  const active = Boolean(words.trim() || who);
  const search = useSearch(
    {
      query: words,
      ...(who ? { sender: who } : {}),
      ...datesOf(chosen),
      ...(chosen.attachment ? { has_attachment: true } : {}),
      ...(chosen.category ? { category: chosen.category } : {}),
      ...(chosen.folder ? { location: chosen.folder } : {}),
    },
    active,
  );
  const hits = search.data?.hits ?? [];
  const folderOptions: FilterOption[] = (folders.data?.folders ?? [])
    .filter((row) => !HIDDEN_FOLDERS.has(row.role))
    .map((row) => {
      const name = SPECIAL_ROLES[row.role];
      return { value: row.name, label: name ? t(name) : row.label, count: row.here ?? 0 };
    });
  const counts = new Map<string, number>();
  for (const hit of hits) if (hit.thread.category) counts.set(hit.thread.category, (counts.get(hit.thread.category) ?? 0) + 1);
  const categoryOptions: FilterOption[] = (categories.data?.categories ?? []).filter((row) => !row.proposed).map((row) => ({ value: row.name, label: row.name, ...(counts.has(row.name) ? { count: counts.get(row.name) ?? 0 } : {}) }));
  return (
    <>
      <SearchFilters chosen={chosen} onChange={onChange} folders={folderOptions} categories={categoryOptions} withAttachment />
      {active ? <MeaningNotice /> : null}
      {!active ? <EmptyState icon="search" title={t("search.prompt")} /> : null}
      {active && search.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {search.isError ? <ErrorState title={t("search.error")} onRetry={() => void search.refetch()} /> : null}
      {active && search.isSuccess && hits.length === 0 ? <EmptyState icon="search" title={t("search.none")} /> : null}
      <ul aria-label={t("search.results")} className="flex flex-col gap-1">
        {hits.map((hit) => (
          <li key={hit.thread.id} data-testid="search-hit">
            <ThreadRowView thread={hit.thread} excerpt={hit.excerpt} highlight={words} />
            {hit.matched_by === "meaning" ? (
              <div className="px-3 pb-1">
                <Badge>{t("search.byMeaning")}</Badge>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </>
  );
}

function DocumentHit({ row, words, list }: { row: DocumentRow; words: string; list: readonly { key: string }[] }) {
  const preview = usePreview();
  const actions = useDocumentActions(row, [], list);
  return (
    <li data-testid="search-document">
      <ContextMenu items={actions}>
        <Pressable onClick={() => preview.show({ key: row.key }, list)} className="focus-ring flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors duration-fast hover:bg-surface-sunken">
          <Icon name={row.source === "email" ? "fromEmail" : "documents"} className="h-4 w-4 shrink-0 text-ink-muted" />
          <span className="min-w-0 flex-1 truncate text-md text-ink-primary"><Highlight text={row.name} words={words} /></span>
          {row.place ? <Badge>{row.place}</Badge> : null}
          <span className="shrink-0 text-sm tabular-nums text-ink-muted">{sizeOf(row.size)}</span>
        </Pressable>
      </ContextMenu>
    </li>
  );
}

function DocumentResults({ text, chosen, onChange }: { text: string; chosen: Chosen; onChange: (next: Chosen) => void }) {
  const { words, sender } = parseQuery(text);
  const who = sender ?? chosen.sender;
  const library = useDocuments({ query: words, limit: DOCUMENT_LIMIT, ...(who ? { sender: who } : {}), ...datesOf(chosen), ...(chosen.fileType ? { file_type: chosen.fileType as FileType } : {}) });
  const rows = library.data?.documents ?? [];
  const list = useMemo(() => rows.map((row) => ({ key: row.key })), [rows]);
  const types: FilterOption[] = FILE_TYPES.map((item) => ({ value: item.value, label: t(item.label) }));
  return (
    <>
      <SearchFilters chosen={chosen} onChange={onChange} fileTypes={types} />
      {words ? <MeaningNotice /> : null}
      {library.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {library.isError ? <ErrorState title={t("documents.error")} onRetry={() => void library.refetch()} /> : null}
      {library.isSuccess && !rows.length ? <EmptyState icon="documents" title={t("search.none")} /> : null}
      <ul aria-label={t("search.results")} className="flex flex-col gap-px">
        {rows.map((row) => <DocumentHit key={row.key} row={row} words={words} list={list} />)}
      </ul>
    </>
  );
}

export function SearchScreen() {
  const params = useSearchParams();
  const router = useRouter();
  const typed = params.get("q") ?? "";
  const [text, setText] = useState(typed);
  useEffect(() => setText(typed), [typed]);
  const tab: Tab = params.get("in") === "documents" ? "documents" : "mail";
  const [chosen, setChosen] = useState<Chosen>({});
  const place = (next: Tab) => router.replace(`/search?${new URLSearchParams({ ...(text ? { q: text } : {}), in: next })}`);
  return (
    <div className="mx-auto flex max-w-content flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-serif text-display text-ink-primary">{t("search.title")}</h1>
        <Segmented label={t("search.where")} hideLabel value={tab} options={[{ value: "mail", label: t("search.in.mail") }, { value: "documents", label: t("search.in.documents") }]} onChange={place} />
      </div>
      <Input autoFocus type="search" aria-label={t("search.words")} placeholder={t("search.words.hint")} value={text} onChange={(event) => setText(event.target.value)} />
      {tab === "mail" ? <MailResults text={text} chosen={chosen} onChange={setChosen} /> : <DocumentResults text={text} chosen={chosen} onChange={setChosen} />}
    </div>
  );
}
