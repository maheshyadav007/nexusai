"use client";

import { useRef, useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { useDocuments, useReadingDocuments, useUpload } from "@/ui/client/documents";
import { useAvailableModels, useModelStatus } from "@/ui/client/models";
import { Icon } from "@/ui/icons";
import { Dialog } from "@/ui/primitives/Dialog";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Menu } from "@/ui/primitives/Menu";
import { BareInput, Pressable, RowButton } from "@/ui/primitives/Pressable";
import { Select } from "@/ui/primitives/Select";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";

export interface Attached {
  ref: string;
  label: string;
}

const DEFAULT_MODEL = "default";
const DOCUMENT = "document:";

/** Which model this chat uses. Radix flips the list up or down to fit where it opens. */
export function ModelPicker({ value, onChange }: { value: string | null; onChange: (model: string | null) => void }) {
  const status = useModelStatus();
  const available = useAvailableModels(Boolean(status.data?.connected));
  const models = available.data?.models ?? [];
  if (!models.length) return null;
  const nameOf = (id: string | null | undefined) => models.find((model) => model.id === id)?.name ?? id;
  const options = [{ value: DEFAULT_MODEL, label: t("chat.model.default", { name: nameOf(status.data?.selected_model) ?? "" }) }, ...models.map((model) => ({ value: model.id, label: model.name }))];
  // A model the plan no longer offers still shows, so the box isn't blank.
  if (value && !models.some((model) => model.id === value)) options.push({ value, label: value });
  return (
    <div data-testid="model-picker" className="min-w-0">
      <Select quiet label={t("chat.model")} value={value ?? DEFAULT_MODEL} options={options} onChange={(chosen) => onChange(chosen === DEFAULT_MODEL ? null : chosen)} />
    </div>
  );
}

function FromDocuments({ open, onOpenChange, onPick }: { open: boolean; onOpenChange: (open: boolean) => void; onPick: (item: Attached) => void }) {
  const [search, setSearch] = useState("");
  const library = useDocuments({ query: search });
  const documents = open ? (library.data?.documents ?? []) : [];
  return (
    <Dialog title={t("chat.attach.documents")} open={open} onOpenChange={onOpenChange}>
      <div className="flex flex-col gap-3">
        <Input aria-label={t("documents.search")} placeholder={t("documents.search")} value={search} onChange={(event) => setSearch(event.target.value)} />
        {library.isSuccess && !documents.length ? <EmptyState icon="documents" title={t(search ? "documents.none" : "documents.empty")} /> : null}
        <ul className="flex max-h-popover flex-col gap-px overflow-y-auto">
          {documents.map((document) => (
            <li key={document.key}>
              <RowButton data-testid="attach-document" onClick={() => onPick({ ref: `${DOCUMENT}${document.key}`, label: document.name })}>
                <Icon name={document.source === "email" ? "fromEmail" : "documents"} className="h-4 w-4 shrink-0 text-ink-muted" />
                <span className="min-w-0 truncate text-md text-ink-primary">{document.name}</span>
              </RowButton>
            </li>
          ))}
        </ul>
      </div>
    </Dialog>
  );
}

/** Adds files to what the next message carries, from this computer or from Documents. */
export function AttachMenu({ onAttach }: { onAttach: (items: readonly Attached[]) => void }) {
  const toast = useToast();
  const upload = useUpload();
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(0);
  const [picking, setPicking] = useState(false);
  const add = (files: FileList | null) => {
    const chosen = Array.from(files ?? []);
    if (input.current) input.current.value = "";
    setUploading((count) => count + chosen.length);
    // All of them together, so several files can't overwrite each other in the session's list.
    void Promise.all(
      chosen.map(async (file): Promise<Attached | null> => {
        try {
          const row = await upload.mutateAsync(file);
          return { ref: `${DOCUMENT}${row.key}`, label: row.name };
        } catch (error) {
          toast({ title: error instanceof ApiRequestError ? error.detail.message : t("chat.attach.failed", { name: file.name }) });
          return null;
        } finally {
          setUploading((count) => count - 1);
        }
      }),
    ).then((rows) => {
      const added = rows.filter((row): row is Attached => row !== null);
      if (added.length) onAttach(added);
    });
  };
  return (
    <>
      <Menu
        trigger={<IconButton icon={uploading ? "loading" : "add"} label={t("chat.attach")} tooltip={false} data-testid="attach" className={`p-1 ${uploading ? "[&>svg]:animate-spin" : ""}`} />}
        items={[
          { id: "upload", label: t("chat.attach.upload"), icon: "uploaded", onSelect: () => input.current?.click() },
          { id: "documents", label: t("chat.attach.documents"), icon: "documents", onSelect: () => setPicking(true) },
        ]}
      />
      <BareInput ref={input} data-testid="attach-input" type="file" multiple aria-label={t("chat.attach.upload")} className="sr-only" onChange={(event) => add(event.target.files)} />
      <FromDocuments
        open={picking}
        onOpenChange={setPicking}
        onPick={(item) => {
          onAttach([item]);
          setPicking(false);
        }}
      />
    </>
  );
}

const uploadsIn = (items: readonly Attached[]) => items.flatMap((item) => (item.ref.startsWith(`${DOCUMENT}u:`) ? [item.ref.slice(DOCUMENT.length)] : []));

/** Whether something attached is still being read, so the message waits for its words. */
export function useAttachedReading(items: readonly Attached[]) {
  return useReadingDocuments(uploadsIn(items));
}

export function AttachedChips({ items, reading, onRemove }: { items: readonly Attached[]; reading: ReadonlySet<string>; onRemove: (ref: string) => void }) {
  if (!items.length) return null;
  return (
    <ul aria-label={t("sessions.context")} className="flex flex-wrap items-center gap-1">
      {items.map((item) => (
        <li key={item.ref} data-testid="context-chip" className="flex max-w-full items-center gap-1 rounded-md border border-line-subtle bg-surface-raised py-px pl-2 pr-1 text-sm text-ink-secondary">
          {reading.has(item.ref.slice(DOCUMENT.length)) ? <StatusDot tone="running" /> : null}
          <span className="min-w-0 truncate">{item.label}</span>
          {reading.has(item.ref.slice(DOCUMENT.length)) ? <span className="shrink-0 text-ink-muted">{t("chat.attach.reading")}</span> : null}
          <Pressable aria-label={t("sessions.context.remove", { label: item.label })} onClick={() => onRemove(item.ref)} className="rounded-sm p-px text-ink-muted transition-colors duration-fast hover:text-ink-primary">
            <Icon name="close" className="h-3 w-3" />
          </Pressable>
        </li>
      ))}
    </ul>
  );
}
