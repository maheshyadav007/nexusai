"use client";

import { useRef, useState, type DragEvent } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { documentUrl, useDocument, useDocuments, useRemoveDocument, useSaveFolders, useUpdateDocument, useUpload } from "@/ui/client/documents";
import { useDateTime } from "@/ui/client/format";
import { Icon } from "@/ui/icons";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Sortable } from "@/ui/primitives/Sortable";
import { TextLink } from "@/ui/primitives/TextLink";
import { useToast } from "@/ui/primitives/Toast";
import { t, type StringKey } from "@/ui/strings";

export type DocumentView = "all" | "uploaded" | "from-email";

const VIEWS: Readonly<Record<DocumentView, { title: StringKey; source: "upload" | "email" | null }>> = {
  all: { title: "nav.documents.all", source: null },
  uploaded: { title: "nav.documents.uploaded", source: "upload" },
  "from-email": { title: "nav.documents.fromEmail", source: "email" },
};
const NO_FOLDER = "none";
const ALL_FOLDERS = "all";

const sizeOf = (bytes: number) => new Intl.NumberFormat(undefined, { style: "unit", unit: bytes < 1024 ** 2 ? "kilobyte" : "megabyte", maximumFractionDigits: 1 }).format(bytes < 1024 ** 2 ? bytes / 1024 : bytes / 1024 ** 2);
const messageOf = (error: unknown) => (error instanceof ApiRequestError ? error.detail.message : t("settings.models.error"));

function UploadZone() {
  const toast = useToast();
  const upload = useUpload();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const add = (files: FileList | null) => {
    for (const file of Array.from(files ?? [])) upload.mutate(file, { onSuccess: () => toast({ title: t("documents.added", { name: file.name }) }) });
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
        <Button loading={upload.isPending} onClick={() => input.current?.click()}>
          {t("documents.choose")}
        </Button>
        <input ref={input} data-testid="file-input" type="file" multiple aria-label={t("documents.choose")} className="sr-only" onChange={(event) => add(event.target.files)} />
      </div>
      {upload.isError ? <ErrorState title={t("documents.uploadFailed")} description={messageOf(upload.error)} /> : null}
    </div>
  );
}

function Preview({ documentKey, folders, onClose }: { documentKey: string | null; folders: readonly string[]; onClose: () => void }) {
  const document = useDocument(documentKey);
  const update = useUpdateDocument();
  const remove = useRemoveDocument();
  const row = document.data?.document;
  const [tagText, setTagText] = useState("");
  const tags = row?.tags ?? [];
  const folder = row?.folder ?? NO_FOLDER;
  const save = (changes: { folder?: string | null; tags?: string[] }) => {
    if (row) update.mutate({ key: row.key, folder: row.folder ?? null, tags, ...changes }, { onSuccess: () => void document.refetch() });
  };
  return (
    <Dialog title={row?.name ?? t("documents.preview")} shape="drawer" open={Boolean(documentKey)} onOpenChange={(open) => (open ? null : onClose())}>
      {document.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {document.isError ? <ErrorState title={t("documents.previewFailed")} description={messageOf(document.error)} /> : null}
      {row ? (
        <div className="flex flex-col gap-4">
          {row.risky ? <p className="text-md text-status-danger">{t("documents.risky")}</p> : <a className="focus-ring self-start rounded-sm text-md text-accent-default underline underline-offset-2" href={documentUrl(row.key)}>{t("documents.download")}</a>}
          {row.thread_id ? <TextLink className="self-start text-md" href={`/mail/thread/${row.thread_id}`}>{t("documents.openMessage")}</TextLink> : null}
          <Field label={t("documents.folder")}>{({ invalid, id }) => <Select id={id} invalid={invalid} value={folder} options={[{ value: NO_FOLDER, label: t("documents.noFolder") }, ...folders.map((value) => ({ value, label: value }))]} onChange={(next) => save({ folder: next === NO_FOLDER ? null : next })} />}</Field>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const tag = tagText.trim();
              if (tag && !tags.includes(tag)) save({ tags: [...tags, tag] });
              setTagText("");
            }}
          >
            <Field label={t("documents.addTag")}>{({ invalid, ...control }) => <Input invalid={invalid} value={tagText} onChange={(event) => setTagText(event.target.value)} {...control} />}</Field>
          </form>
          {tags.length ? (
            <ul className="flex flex-wrap gap-1">
              {tags.map((tag) => (
                <li key={tag}>
                  <button type="button" aria-label={t("documents.removeTag", { tag })} className="focus-ring rounded-sm" onClick={() => save({ tags: tags.filter((item) => item !== tag) })}>
                    <Badge>{tag}</Badge>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <section>
            <h3 className="mb-2 text-md font-medium">{t("documents.text")}</h3>
            <div data-testid="document-text" className="max-h-popover overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-surface-sunken p-3 text-sm text-ink-secondary">{document.data?.text || t("documents.noText")}</div>
          </section>
          {row.source === "upload" ? (
            <div>
              <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate(row.key, { onSuccess: onClose })}>
                {t("documents.remove")}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </Dialog>
  );
}

function Folders({ folders, current, onChoose }: { folders: readonly string[]; current: string; onChoose: (folder: string) => void }) {
  const save = useSaveFolders();
  const [name, setName] = useState("");
  const row = (value: string, label: string) => (
    <button type="button" aria-current={current === value ? "true" : undefined} onClick={() => onChoose(value)} className={`focus-ring w-full truncate rounded-md px-2 py-1 text-left text-md transition-colors duration-fast ${current === value ? "bg-surface-sunken font-medium text-ink-primary" : "text-ink-secondary hover:bg-surface-sunken"}`}>
      {label}
    </button>
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
        <Field label={t("documents.newFolder")}>{({ invalid, ...control }) => <Input invalid={invalid} value={name} onChange={(event) => setName(event.target.value)} {...control} />}</Field>
      </form>
    </nav>
  );
}

export function DocumentsScreen({ view }: { view: DocumentView }) {
  const config = VIEWS[view];
  const [query, setQuery] = useState("");
  const [folder, setFolder] = useState(ALL_FOLDERS);
  const [open, setOpen] = useState<string | null>(null);
  const format = useDateTime();
  const library = useDocuments({ query, ...(config.source ? { source: config.source } : {}), ...(folder === ALL_FOLDERS ? {} : { folder }) });
  const documents = library.data?.documents ?? [];
  const folders = library.data?.folders ?? [];
  return (
    <div className="mx-auto flex max-w-page flex-col gap-4 p-6">
      <h1 className="font-serif text-display text-ink-primary">{t(config.title)}</h1>
      {view !== "from-email" ? <UploadZone /> : null}
      <div className="flex items-start gap-6">
        <Folders folders={folders} current={folder} onChoose={setFolder} />
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <Field label={t("documents.search")}>{({ invalid, ...control }) => <Input invalid={invalid} value={query} onChange={(event) => setQuery(event.target.value)} {...control} />}</Field>
          {library.isPending ? <Skeleton className="h-6 w-full" /> : null}
          {library.isError ? <ErrorState title={t("documents.error")} onRetry={() => void library.refetch()} /> : null}
          {library.isSuccess && documents.length === 0 ? <EmptyState icon="documents" title={t(query ? "documents.none" : "documents.empty")} /> : null}
          <ul aria-label={t(config.title)} className="flex flex-col gap-px">
            {documents.map((document) => (
              <li key={document.key}>
                <button type="button" data-testid="document-row" onClick={() => setOpen(document.key)} className="focus-ring flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors duration-fast hover:bg-surface-sunken">
                  <Icon name={document.source === "email" ? "fromEmail" : "documents"} className="h-4 w-4 shrink-0 text-ink-muted" />
                  <span className="min-w-0 flex-1 truncate text-md text-ink-primary">{document.name}</span>
                  {document.risky ? <Badge tone="danger">{t("documents.riskyBadge")}</Badge> : null}
                  {document.folder ? <Badge>{document.folder}</Badge> : null}
                  {(document.tags ?? []).map((tag) => (
                    <Badge key={tag}>{tag}</Badge>
                  ))}
                  <span className="shrink-0 text-sm tabular-nums text-ink-muted">{sizeOf(document.size)}</span>
                  <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(document.date)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <Preview documentKey={open} folders={folders} onClose={() => setOpen(null)} />
    </div>
  );
}
