"use client";

import { useRef, useState, type DragEvent } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { documentUrl, useDocument, useDocuments, useReadAgain, useRemoveDocument, useSaveFolders, useUpdateDocument, useUpload } from "@/ui/client/documents";
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
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Sortable } from "@/ui/primitives/Sortable";
import { StatusDot } from "@/ui/primitives/StatusDot";
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

function Preview({ documentKey, folders, onClose }: { documentKey: string | null; folders: readonly string[]; onClose: () => void }) {
  const document = useDocument(documentKey);
  const update = useUpdateDocument();
  const remove = useRemoveDocument();
  const readAgain = useReadAgain();
  const row = document.data?.document;
  // Reading happens in the background, and the event that says it's done brings this up to date.
  const reading = row?.status === "pending";
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
          {row.thread_id ? <TextLink className="self-start text-md" href={`/mail/all/${row.thread_id}`}>{t("documents.openMessage")}</TextLink> : null}
          {row.risky ? null : <div><AskAgent context={[`document:${row.key}`]} title={row.name} /></div>}
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
                  <Pressable aria-label={t("documents.removeTag", { tag })} className="rounded-sm" onClick={() => save({ tags: tags.filter((item) => item !== tag) })}>
                    <Badge>{tag}</Badge>
                  </Pressable>
                </li>
              ))}
            </ul>
          ) : null}
          {row.status_reason ? (
            <div className="flex flex-col items-start gap-2 rounded-md bg-surface-sunken p-3">
              <p data-testid="document-reason" className="text-md text-ink-secondary">{row.status_reason}</p>
              <Button loading={readAgain.isPending} onClick={() => readAgain.mutate(row.key, { onSuccess: () => void document.refetch() })}>
                {t("documents.readAgain")}
              </Button>
            </div>
          ) : null}
          {reading ? <p className="text-md text-ink-muted">{t("documents.status.pending")}</p> : null}
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
          {query.trim() ? <MeaningNotice /> : null}
          <Input aria-label={t("documents.search")} placeholder={t("documents.search")} value={query} onChange={(event) => setQuery(event.target.value)} />
          {library.isPending ? <Skeleton className="h-6 w-full" /> : null}
          {library.isError ? <ErrorState title={t("documents.error")} onRetry={() => void library.refetch()} /> : null}
          {library.isSuccess && documents.length === 0 ? <EmptyState icon="documents" title={t(query ? "documents.none" : "documents.empty")} /> : null}
          <ul aria-label={t(config.title)} className="flex flex-col gap-px">
            {documents.map((document) => (
              <li key={document.key}>
                <Pressable data-testid="document-row" onClick={() => setOpen(document.key)} className="focus-ring flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors duration-fast hover:bg-surface-sunken">
                  <Icon name={document.source === "email" ? "fromEmail" : "documents"} className="h-4 w-4 shrink-0 text-ink-muted" />
                  <span className="min-w-0 flex-1 truncate text-md text-ink-primary">{document.name}</span>
                  {document.risky ? <Badge tone="danger">{t("documents.riskyBadge")}</Badge> : <StatusBadge status={document.status} />}
                  {document.folder ? <Badge>{document.folder}</Badge> : null}
                  {(document.tags ?? []).map((tag) => (
                    <Badge key={tag}>{tag}</Badge>
                  ))}
                  <span className="shrink-0 text-sm tabular-nums text-ink-muted">{sizeOf(document.size)}</span>
                  <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(document.date)}</span>
                </Pressable>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <Preview documentKey={open} folders={folders} onClose={() => setOpen(null)} />
    </div>
  );
}
