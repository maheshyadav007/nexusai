"use client";

import { useState } from "react";
import type { Panel, PanelBoard as Board } from "@/ui/client/contracts.generated";
import { useDateTime } from "@/ui/client/format";
import { usePanelBoard, usePanelResults, useResetBoard, useSaveBoard } from "@/ui/client/documents";
import { ThreadRowView } from "@/ui/features/mail/ThreadRowView";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { Dialog } from "@/ui/primitives/Dialog";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Sortable } from "@/ui/primitives/Sortable";
import { t } from "@/ui/strings";

const SOURCES = [
  { value: "threads", label: t("panels.source.threads") },
  { value: "documents", label: t("panels.source.documents") },
];
const SIZES = [
  { value: "small", label: t("panels.size.small") },
  { value: "medium", label: t("panels.size.medium") },
  { value: "large", label: t("panels.size.large") },
] as const;
const SPANS: Readonly<Record<string, string>> = { small: "col-span-1", medium: "col-span-2", large: "col-span-3" };

function PanelResults({ panel }: { panel: Panel }) {
  const results = usePanelResults(panel);
  const format = useDateTime();
  if (results.isPending) return <Skeleton className="h-6 w-full" />;
  if (results.isError) return <ErrorState title={t("panels.error")} onRetry={() => void results.refetch()} />;
  const threads = results.data.threads ?? [];
  const documents = results.data.documents ?? [];
  if (!threads.length && !documents.length) return <p className="text-md text-ink-muted">{t("panels.empty")}</p>;
  return (
    <ul className="flex max-h-popover flex-col gap-px overflow-y-auto">
      {threads.map((thread) => (
        <li key={thread.id}>
          <ThreadRowView thread={thread} />
        </li>
      ))}
      {documents.map((document) => (
        <li key={document.key} className="flex items-baseline justify-between gap-3 px-3 py-1">
          <span className="min-w-0 truncate text-md text-ink-primary">{document.name}</span>
          <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(document.date)}</span>
        </li>
      ))}
    </ul>
  );
}

function PanelBuilder({ onAdd }: { onAdd: (panel: Panel) => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [source, setSource] = useState<"threads" | "documents">("threads");
  const [sender, setSender] = useState("");
  const [subject, setSubject] = useState("");
  const [query, setQuery] = useState("");
  const [unread, setUnread] = useState(false);
  const [flagged, setFlagged] = useState(false);
  const create = () => {
    const filters = source === "threads" ? { ...(sender ? { sender } : {}), ...(subject ? { subject } : {}), unread_only: unread, flagged_only: flagged } : { ...(query ? { query } : {}) };
    onAdd({ id: `panel-${crypto.randomUUID().slice(0, 8)}`, title: title.trim(), source, filters, size: "medium" });
    setOpen(false);
    setTitle("");
  };
  return (
    <Dialog title={t("panels.add")} description={t("panels.add.description")} open={open} onOpenChange={setOpen} trigger={<Button variant="primary">{t("panels.add")}</Button>}>
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          create();
        }}
      >
        <Field label={t("panels.name")}>{({ invalid, ...control }) => <Input invalid={invalid} value={title} onChange={(event) => setTitle(event.target.value)} {...control} />}</Field>
        <Field label={t("panels.source")}>{({ invalid, id }) => <Select id={id} invalid={invalid} value={source} options={SOURCES} onChange={(value) => setSource(value as typeof source)} />}</Field>
        {source === "threads" ? (
          <>
            <Field label={t("panels.sender")}>{({ invalid, ...control }) => <Input invalid={invalid} value={sender} onChange={(event) => setSender(event.target.value)} {...control} />}</Field>
            <Field label={t("panels.subject")}>{({ invalid, ...control }) => <Input invalid={invalid} value={subject} onChange={(event) => setSubject(event.target.value)} {...control} />}</Field>
            <Checkbox label={t("panels.unread")} checked={unread} onChange={setUnread} />
            <Checkbox label={t("panels.flagged")} checked={flagged} onChange={setFlagged} />
          </>
        ) : (
          <Field label={t("panels.query")}>{({ invalid, ...control }) => <Input invalid={invalid} value={query} onChange={(event) => setQuery(event.target.value)} {...control} />}</Field>
        )}
        <div>
          <Button type="submit" variant="primary" disabled={!title.trim()}>
            {t("panels.create")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function PanelBoard() {
  const board = usePanelBoard();
  const save = useSaveBoard();
  const reset = useResetBoard();
  const panels = board.data?.panels ?? [];
  const store = (next: Board["panels"]) => save.mutate({ panels: next });
  return (
    <div className="mx-auto flex max-w-page flex-col gap-4 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-serif text-display text-ink-primary">{t("nav.panels")}</h1>
          <p className="mt-1 text-md text-ink-muted">{t("panels.description")}</p>
        </div>
        <div className="flex gap-2">
          <Button loading={reset.isPending} onClick={() => reset.mutate()}>{t("panels.reset")}</Button>
          <PanelBuilder onAdd={(panel) => store([...panels, panel])} />
        </div>
      </header>
      {board.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {board.isError ? <ErrorState title={t("panels.error")} onRetry={() => void board.refetch()} /> : null}
      {board.isSuccess && panels.length === 0 ? <EmptyState icon="panels" title={t("panels.none")} /> : null}
      <Sortable
        label={t("nav.panels")}
        layout="grid"
        items={panels.map((panel) => ({
          id: panel.id,
          label: panel.title,
          className: SPANS[panel.size ?? "medium"] ?? "col-span-2",
          content: (
            <section data-testid="panel" aria-label={panel.title} className="flex flex-col gap-3 rounded-lg border border-line-subtle bg-surface-raised p-4">
              <header className="flex items-center justify-between gap-2">
                <h2 className="min-w-0 truncate text-md font-medium text-ink-primary">{panel.title}</h2>
                <div className="flex items-center gap-1">
                  <Select quiet label={t("panels.size")} value={panel.size ?? "medium"} options={SIZES} onChange={(size) => store(panels.map((item) => (item.id === panel.id ? { ...item, size: size as NonNullable<typeof item.size> } : item)))} />
                  <IconButton icon="close" label={t("panels.remove", { name: panel.title })} onClick={() => store(panels.filter((item) => item.id !== panel.id))} />
                </div>
              </header>
              <PanelResults panel={panel} />
            </section>
          ),
        }))}
        onReorder={(ids) => store(ids.flatMap((id) => panels.find((panel) => panel.id === id) ?? []))}
      />
    </div>
  );
}
