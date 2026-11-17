"use client";

import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { DocumentRow } from "@/ui/client/contracts.generated";
import { documentUrl, useDocument, useDocumentReader, useDocuments, useReadAgain, useRemoveDocument, useUpdateDocument } from "@/ui/client/documents";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { useOpenSource } from "@/ui/features/sources/context";
import { documentSource, fullHref, mailSource, pageNumber, type PreviewSource } from "@/ui/features/sources/kinds";
import { PreviewFrame, type PreviewProps } from "@/ui/features/sources/PreviewFrame";
import { Icon } from "@/ui/icons";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import type { MenuItem } from "@/ui/primitives/Menu";
import { Pressable } from "@/ui/primitives/Pressable";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { TextLink } from "@/ui/primitives/TextLink";
import { t } from "@/ui/strings";
import { DocumentViewer } from "./DocumentViewer";

const NO_FOLDER = "none";

/** What can be done to a document. The toolbar and the right-click menu read this one list. */
export function useDocumentActions(row: DocumentRow, _folders: readonly string[] = [], list: readonly PreviewSource[] = []): MenuItem[] {
  const sources = useOpenSource();
  const assistant = useAssistant();
  const remove = useRemoveDocument();
  return [
    { id: "open", label: t("menu.open"), onSelect: () => sources.open(documentSource(row.key), list) },
    ...(row.risky ? [] : [{ id: "download", label: t("documents.download"), onSelect: () => window.location.assign(documentUrl(row.key)) }]),
    ...(row.thread_id ? [{ id: "message", label: t("documents.openMessage"), onSelect: () => sources.openFull(mailSource(row.thread_id as number)) }] : []),
    ...(row.risky ? [] : [{ id: "ask", label: t("menu.askAgent"), icon: "chat" as const, onSelect: () => assistant.start({ context: [`document:${row.key}`], title: row.name }) }]),
    ...(row.source === "upload" ? [{ id: "remove", label: t("documents.remove"), icon: "trash" as const, danger: true, onSelect: () => remove.mutate(row.key) }] : []),
  ];
}

function Details({ documentKey }: { documentKey: string }) {
  const document = useDocument(documentKey);
  const library = useDocuments({ limit: 1 });
  const update = useUpdateDocument();
  const readAgain = useReadAgain();
  const row = document.data?.document;
  const folders = library.data?.folders ?? [];
  const [tagText, setTagText] = useState("");
  if (!row) return <Skeleton className="h-6 w-full" />;
  const tags = row.tags ?? [];
  const save = (changes: { folder?: string | null; tags?: string[] }) => update.mutate({ key: row.key, folder: row.folder ?? null, tags, ...changes }, { onSuccess: () => void document.refetch() });
  return (
    <aside aria-label={t("documents.info")} className="flex w-rail-wide shrink-0 flex-col gap-4 overflow-y-auto">
      <Field label={t("documents.folder")}>{({ invalid, id }) => <Select id={id} invalid={invalid} value={row.folder ?? NO_FOLDER} options={[{ value: NO_FOLDER, label: t("documents.noFolder") }, ...folders.map((name) => ({ value: name, label: name }))]} onChange={(value) => save({ folder: value === NO_FOLDER ? null : value })} />}</Field>
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
          <Button loading={readAgain.isPending} onClick={() => readAgain.mutate(row.key, { onSuccess: () => void document.refetch() })}>{t("documents.readAgain")}</Button>
        </div>
      ) : null}
      {row.status === "pending" ? <p className="text-md text-ink-muted">{t("documents.status.pending")}</p> : null}
      <section>
        <h3 className="mb-2 text-md font-medium">{t("documents.text")}</h3>
        <div data-testid="document-text" className="max-h-popover overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-surface-sunken p-3 text-sm text-ink-secondary">{document.data?.text || t("documents.noText")}</div>
      </section>
    </aside>
  );
}

/** A document or a Home file in the quick preview. */
export function DocumentPreviewPanel(props: PreviewProps) {
  const { source, onClose } = props;
  const target = source.kind === "file" ? { path: source.ref } : { key: source.ref };
  const reader = useDocumentReader(target);
  const document = useDocument(target.key ?? null);
  const remove = useRemoveDocument();
  const sources = useOpenSource();
  const [info, setInfo] = useState(false);
  const data = reader.data;
  const row = document.data?.document;
  const actions = (
    <>
      {data && !row?.risky ? <a className="focus-ring rounded-md px-2 py-1 text-md text-accent-default underline underline-offset-2" href={data.url}>{t("documents.download")}</a> : null}
      {row?.thread_id ? <TextLink className="px-2 text-md" href={fullHref(mailSource(row.thread_id))} onClick={(event) => { event.preventDefault(); sources.open(mailSource(row.thread_id as number)); }}>{t("documents.openMessage")}</TextLink> : null}
      {data?.key && !row?.risky ? <AskAgent context={[`document:${data.key}`]} title={data.name} /> : null}
      {target.key ? <Button variant="quiet" aria-pressed={info} onClick={() => setInfo(!info)}><Icon name="info" />{t("documents.info")}</Button> : null}
      {row?.source === "upload" ? <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate(row.key, { onSuccess: onClose })}>{t("documents.remove")}</Button> : null}
    </>
  );
  return (
    <PreviewFrame {...props} title={data?.name ?? t("documents.preview")} testId="document-preview" actions={actions}>
      <div className="flex min-h-0 flex-1 gap-4">
        <div className="min-h-0 min-w-0 flex-1 overflow-auto rounded-md bg-surface-page p-3">
          {row?.risky ? <p className="text-md text-status-danger">{t("documents.risky")}</p> : null}
          {reader.isPending ? <Skeleton className="h-6 w-full" /> : null}
          {reader.isError ? <ErrorState title={t("documents.previewFailed")} description={reader.error instanceof ApiRequestError ? reader.error.detail.message : ""} /> : null}
          {data?.status_reason && data.text ? <p className="mb-2 text-sm text-ink-muted">{data.status_reason}</p> : null}
          {data && !row?.risky ? <DocumentViewer reader={data} page={pageNumber(source.page)} /> : null}
        </div>
        {info && target.key ? <Details documentKey={target.key} /> : null}
      </div>
    </PreviewFrame>
  );
}
