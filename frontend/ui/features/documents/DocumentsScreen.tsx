"use client";

import type { DocumentRow } from "@/ui/client/contracts.generated";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { useDocumentActions, usePreview } from "./DocumentPreview";
import { sizeOf } from "./sizes";
import { useRouter } from "next/navigation";
import { useRef, useState, type DragEvent, useMemo } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { useDocuments, useSaveFolders, useUpdateDocument, useUpload } from "@/ui/client/documents";
import { useDateTime } from "@/ui/client/format";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { MeaningNotice } from "@/ui/features/settings/LocalModelSettings";
import { Icon } from "@/ui/icons";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { BareInput, Pressable } from "@/ui/primitives/Pressable";
import { Segmented } from "@/ui/primitives/Segmented";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Sortable } from "@/ui/primitives/Sortable";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { TextLink } from "@/ui/primitives/TextLink";
import { useToast } from "@/ui/primitives/Toast";
import { t, type StringKey } from "@/ui/strings";
import { HomeFolderView } from "./HomeFolderView";

export type DocumentView = "all" | "uploaded" | "from-email" | "home";

const VIEWS: Readonly<Record<Exclude<DocumentView, "home">, { title: StringKey; source: "upload" | "email" | null }>> = {
  all: { title: "nav.documents.all", source: null },
  uploaded: { title: "nav.documents.uploaded", source: "upload" },
  "from-email": { title: "nav.documents.fromEmail", source: "email" },
};
const NO_FOLDER = "none";
const ALL_FOLDERS = "all";

const messageOf = (error: unknown) => (error instanceof ApiRequestError ? error.detail.message : t("settings.models.error"));

interface Adding {
  id: number;
  name: string;
  error?: string;
}

/** Many files at once: each shows how it went, and one failing doesn't affect the others. */
function UploadZone() {
  const toast = useToast();
  const upload = useUpload();
  const input = useRef<HTMLInputElement>(null);
  const counter = useRef(0);
  const [over, setOver] = useState(false);
  const [adding, setAdding] = useState<readonly Adding[]>([]);
  const finish = (id: number) => setAdding((rows) => rows.filter((row) => row.id !== id));
  const add = (files: FileList | null) => {
    for (const file of Array.from(files ?? [])) {
      const id = (counter.current += 1);
      setAdding((rows) => [...rows, { id, name: file.name }]);
      // Not mutate: its callbacks only run for the last call, and each file needs its own answer.
      upload.mutateAsync(file).then(
        (row) => {
          finish(id);
          toast({ title: t(row.duplicate ? "documents.duplicate" : "documents.added", { name: row.name }) });
        },
        (error: unknown) => setAdding((rows) => rows.map((item) => (item.id === id ? { ...item, error: messageOf(error) } : item))),
      );
    }
    if (input.current) input.current.value = "";
  };
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setOver(false);
    add(event.dataTransfer.files);
  };
  return (
    <div className="flex flex-col gap-2">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={`flex flex-wrap items-center justify-between gap-3 rounded-md border border-dashed p-4 transition-colors duration-fast ${over ? "border-accent-default bg-surface-sunken" : "border-line-strong"}`}
      >
        <p className="text-md text-ink-secondary">{t("documents.drop")}</p>
        <Button onClick={() => input.current?.click()}>{t("documents.choose")}</Button>
        <BareInput ref={input} data-testid="file-input" type="file" multiple aria-label={t("documents.choose")} className="sr-only" onChange={(event) => add(event.target.files)} />
      </div>
      {adding.length ? (
        <ul aria-label={t("documents.adding")} className="flex flex-col gap-1">
          <Presence>
            {adding.map((row) => (
              <Rise as="li" key={row.id} settle="position" data-testid="upload-row" className="flex items-center gap-2 rounded-md bg-surface-sunken px-3 py-1 text-sm">
                <Icon name={row.error ? "error" : "loading"} className={`h-3 w-3 shrink-0 ${row.error ? "text-status-danger" : "animate-spin text-ink-muted"}`} />
                <span className="min-w-0 flex-1 truncate text-ink-primary">{row.name}</span>
                {row.error ? <span role="alert" className="min-w-0 truncate text-status-danger">{row.error}</span> : <span className="text-ink-muted">{t("documents.addingOne")}</span>}
                {row.error ? <IconButton icon="close" label={t("documents.dismissFailed", { name: row.name })} onClick={() => finish(row.id)} /> : null}
              </Rise>
            ))}
          </Presence>
        </ul>
      ) : null}
    </div>
  );
}

const STATUS_LABEL: Readonly<Record<string, StringKey>> = {
  image: "documents.status.image",
  encrypted: "documents.status.encrypted",
  unsupported: "documents.status.unsupported",
  too_large: "documents.status.tooLarge",
  failed: "documents.status.failed",
  no_text: "documents.status.noText",
  empty: "documents.status.noText",
};

function StatusBadge({ status }: { status: string | undefined }) {
  if (status === "pending") {
    return (
      <span data-testid="document-status" className="flex shrink-0 items-center gap-1 text-sm text-ink-muted">
        <StatusDot tone="running" />
        {t("documents.status.pending")}
      </span>
    );
  }
  const label = status ? STATUS_LABEL[status] : undefined;
  return label ? (
    <span data-testid="document-status">
      <Badge tone={status === "failed" ? "danger" : "neutral"}>{t(label)}</Badge>
    </span>
  ) : null;
}

function Folders({ folders, current, onChoose }: { folders: readonly string[]; current: string; onChoose: (folder: string) => void }) {
  const save = useSaveFolders();
  const [name, setName] = useState("");
  const row = (value: string, label: string) => (
    <Pressable aria-current={current === value ? "true" : undefined} onClick={() => onChoose(value)} className={`focus-ring w-full truncate rounded-md px-2 py-1 text-left text-md transition-colors duration-fast ${current === value ? "bg-surface-sunken font-medium text-ink-primary" : "text-ink-secondary hover:bg-surface-sunken"}`}>
      {label}
    </Pressable>
  );
  return (
    <nav aria-label={t("documents.folders")} className="flex w-sidebar shrink-0 flex-col gap-2">
      {row(ALL_FOLDERS, t("documents.allFolders"))}
      <Sortable label={t("documents.folders")} items={folders.map((folder) => ({ id: folder, label: folder, content: row(folder, folder) }))} onReorder={(ids) => save.mutate(ids)} />
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const clean = name.trim();
          if (clean && !folders.includes(clean)) save.mutate([...folders, clean]);
          setName("");
        }}
      >
        <Input aria-label={t("documents.newFolder")} placeholder={t("documents.newFolder")} value={name} onChange={(event) => setName(event.target.value)} />
      </form>
    </nav>
  );
}

function ViewFilter({ view }: { view: DocumentView }) {
  const router = useRouter();
  const options: readonly { value: DocumentView; label: string }[] = [
    { value: "all", label: t("documents.view.all") },
    { value: "from-email", label: t("documents.view.email") },
    { value: "uploaded", label: t("documents.view.uploaded") },
    { value: "home", label: t("documents.view.home") },
  ];
  return <Segmented label={t("documents.view")} hideLabel value={view} options={options} onChange={(next) => router.push(`/documents/${next}`)} />;
}

export function DocumentsScreen({ view }: { view: DocumentView }) {
  if (view === "home") {
    return (
      <div className="mx-auto flex max-w-page flex-col gap-4 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="font-serif text-display text-ink-primary">{t("nav.documents")}</h1>
          <ViewFilter view={view} />
        </div>
        <HomeFolderView />
      </div>
    );
  }
  return <Library view={view} />;
}

function LibraryRow({ document, list, onOpen, format }: { document: DocumentRow; list: readonly { key: string }[]; onOpen: () => void; format: (value: string) => string }) {
  const actions = useDocumentActions(document, [], list);
  return (
    <li>
      <ContextMenu items={actions}>
        <Pressable data-testid="document-row" onClick={onOpen} className="focus-ring flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors duration-fast hover:bg-surface-sunken">
          <Icon name={document.source === "email" ? "fromEmail" : document.source === "home" ? "agent" : "documents"} className="h-4 w-4 shrink-0 text-ink-muted" />
          <span className="min-w-0 flex-1 truncate text-md text-ink-primary">{document.name}</span>
          {document.risky ? <Badge tone="danger">{t("documents.riskyBadge")}</Badge> : <StatusBadge status={document.status} />}
          {document.place ? <span data-testid="document-place"><Badge>{document.place}</Badge></span> : null}
          {document.folder ? <Badge>{document.folder}</Badge> : null}
          {(document.tags ?? []).map((tag) => (
            <Badge key={tag}>{tag}</Badge>
          ))}
          <span className="shrink-0 text-sm tabular-nums text-ink-muted">{sizeOf(document.size)}</span>
          <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(document.date)}</span>
        </Pressable>
      </ContextMenu>
    </li>
  );
}

function Library({ view }: { view: Exclude<DocumentView, "home"> }) {
  const config = VIEWS[view];
  const [query, setQuery] = useState("");
  const [folder, setFolder] = useState(ALL_FOLDERS);
  const preview = usePreview();
  const format = useDateTime();
  const library = useDocuments({ query, ...(config.source ? { source: config.source } : {}), ...(folder === ALL_FOLDERS ? {} : { folder }) });
  const documents = library.data?.documents ?? [];
  const folders = library.data?.folders ?? [];
  const list = useMemo(() => documents.map((row) => ({ key: row.key })), [documents]);
  return (
    <div className="mx-auto flex max-w-page flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-serif text-display text-ink-primary">{t(config.title)}</h1>
        <ViewFilter view={view} />
      </div>
      {view !== "from-email" ? <UploadZone /> : null}
      <div className="flex items-start gap-6">
        <Folders folders={folders} current={folder} onChoose={setFolder} />
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          {query.trim() ? <MeaningNotice /> : null}
          <Input aria-label={t("documents.search")} placeholder={t("documents.search")} value={query} onChange={(event) => setQuery(event.target.value)} />
          {library.isPending ? <Skeleton className="h-6 w-full" /> : null}
          {library.isError ? <ErrorState title={t("documents.error")} onRetry={() => void library.refetch()} /> : null}
          {library.isSuccess && documents.length === 0 ? <EmptyState icon="documents" title={t(query ? "documents.none" : "documents.empty")} /> : null}
          <ul aria-label={t(config.title)} className="flex flex-col gap-px">
            {documents.map((document) => <LibraryRow key={document.key} document={document} list={list} onOpen={() => preview.show({ key: document.key }, list)} format={format} />)}
          </ul>
        </div>
      </div>
    </div>
  );
}
