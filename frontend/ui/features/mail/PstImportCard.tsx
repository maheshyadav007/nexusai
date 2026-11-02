"use client";

import { useRef, useState, type DragEvent } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { uploadPst, useAddPst, useFindPst, usePausePst, usePstImports, usePstSearch, useResumePst, useStopFindPst } from "@/ui/client/documents";
import { useDateOnly } from "@/ui/client/format";
import { useHomeStatus } from "@/ui/client/home";
import { FolderPicker } from "@/ui/features/home/FolderPicker";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { BareInput } from "@/ui/primitives/Pressable";
import { Progress } from "@/ui/primitives/Progress";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { t, type StringKey } from "@/ui/strings";

const STATES: Readonly<Record<string, { label: StringKey; tone: "running" | "waiting" | "done" | "failed" }>> = {
  queued: { label: "pst.status.queued", tone: "waiting" },
  running: { label: "pst.status.running", tone: "running" },
  paused: { label: "pst.status.paused", tone: "waiting" },
  done: { label: "pst.status.done", tone: "done" },
  failed: { label: "pst.status.failed", tone: "failed" },
};

const sizeOf = (bytes: number) => new Intl.NumberFormat(undefined, { style: "unit", unit: bytes < 1024 ** 3 ? "megabyte" : "gigabyte", maximumFractionDigits: 1 }).format(bytes / (bytes < 1024 ** 3 ? 1024 ** 2 : 1024 ** 3));
const messageOf = (error: unknown) => (error instanceof ApiRequestError ? error.detail.message : t("pst.addFailed"));

/** Goes looking only when asked. On Windows, Outlook's archives are usually in a few known places. */
function FindFiles({ added }: { added: ReadonlySet<string> }) {
  const search = usePstSearch();
  const find = useFindPst();
  const stop = useStopFindPst();
  const add = useAddPst();
  const format = useDateOnly();
  const state = search.data?.state ?? "idle";
  const running = state === "running";
  const found = search.data?.found ?? [];
  return (
    <section aria-label={t("pst.find")} className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button loading={find.isPending} disabled={running} onClick={() => find.mutate(false)}>{t("pst.find")}</Button>
        {state === "done" && !search.data?.everywhere ? <Button variant="quiet" onClick={() => find.mutate(true)}>{t("pst.find.everywhere")}</Button> : null}
        {running ? <Button variant="quiet" onClick={() => stop.mutate(undefined)}>{t("pst.find.stop")}</Button> : null}
      </div>
      {running ? <p role="status" data-testid="pst-searching" className="truncate text-sm text-ink-muted">{t("pst.find.looking", { place: search.data?.place ?? "" })}</p> : null}
      {state === "done" && !found.length ? <p role="status" className="text-sm text-ink-muted">{t("pst.find.none")}</p> : null}
      {found.length ? (
        <ul className="flex flex-col border-t border-line-subtle">
          {found.map((file) => (
            <li key={file.path} data-testid="pst-found" className="flex items-center justify-between gap-3 border-b border-line-subtle py-2">
              <span className="flex min-w-0 flex-col">
                <span className="truncate text-md text-ink-primary">{file.name}</span>
                <span className="truncate text-sm tabular-nums text-ink-muted">{sizeOf(file.size)} · {format(file.modified)} · {file.path}</span>
              </span>
              {added.has(file.path) ? <span className="shrink-0 text-sm text-ink-muted">{t("pst.find.added")}</span> : <Button className="shrink-0" onClick={() => add.mutate(file.path)}>{t("pst.add")}</Button>}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

interface Sending {
  id: number;
  name: string;
  size: number;
  received: number;
  error?: string;
}

/** For a file the backend can't be pointed at. It keeps a copy, because attachments read from it. */
function SendFile() {
  const add = useAddPst();
  const input = useRef<HTMLInputElement>(null);
  const counter = useRef(0);
  const [over, setOver] = useState(false);
  const [sending, setSending] = useState<readonly Sending[]>([]);
  const change = (id: number, changes: Partial<Sending>) => setSending((rows) => rows.map((row) => (row.id === id ? { ...row, ...changes } : row)));
  const send = (files: FileList | null) => {
    for (const file of Array.from(files ?? [])) {
      const id = (counter.current += 1);
      setSending((rows) => [...rows, { id, name: file.name, size: file.size, received: 0 }]);
      uploadPst(file, (received) => change(id, { received })).then(
        (path) => {
          setSending((rows) => rows.filter((row) => row.id !== id));
          add.mutate(path);
        },
        (error: unknown) => change(id, { error: messageOf(error) }),
      );
    }
    if (input.current) input.current.value = "";
  };
  const drop = (event: DragEvent) => {
    event.preventDefault();
    setOver(false);
    send(event.dataTransfer.files);
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
        className={`flex flex-wrap items-center justify-between gap-3 rounded-md border border-dashed p-3 transition-colors duration-fast ${over ? "border-accent-default bg-surface-sunken" : "border-line-strong"}`}
      >
        <p className="text-sm text-ink-secondary">{t("pst.upload.drop")}</p>
        <Button onClick={() => input.current?.click()}>{t("pst.upload")}</Button>
        <BareInput ref={input} data-testid="pst-input" type="file" multiple accept=".pst,.ost" aria-label={t("pst.upload")} className="sr-only" onChange={(event) => send(event.target.files)} />
      </div>
      {sending.map((row) => (
        <div key={row.id} data-testid="pst-upload" className="flex flex-col gap-1 rounded-md border border-line-subtle p-3">
          <span className="truncate text-md text-ink-primary">{row.name}</span>
          <Progress label={t("pst.upload.progress", { name: row.name })} value={row.received} max={Math.max(row.size, 1)} />
          {row.error ? <p role="alert" className="text-sm text-status-danger">{row.error}</p> : <p className="text-sm tabular-nums text-ink-muted">{t("pst.upload.count", { done: sizeOf(row.received), total: sizeOf(row.size) })}</p>}
        </div>
      ))}
    </div>
  );
}

export function PstImportCard() {
  const imports = usePstImports();
  const add = useAddPst();
  const pause = usePausePst();
  const resume = useResumePst();
  const home = useHomeStatus();
  const [path, setPath] = useState("");
  const items = imports.data?.imports ?? [];
  return (
    <Card title={t("pst.title")} description={t("pst.description")}>
      <div className="flex flex-col gap-4">
        <FindFiles added={new Set(items.map((item) => item.path))} />
        <form
          className="flex flex-col items-start gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            add.mutate(path.trim(), { onSuccess: () => setPath("") });
          }}
        >
          <div className="w-full">
            <Field label={t("pst.file")} hint={t("pst.file.hint")} {...(add.isError ? { error: messageOf(add.error) } : {})}>
              {({ invalid, ...control }) => (
                <div className="flex items-center gap-2">
                  <Input invalid={invalid} spellCheck={false} value={path} onChange={(event) => setPath(event.target.value)} {...control} />
                  <FolderPicker start={home.data?.path ?? home.data?.default_path ?? ""} extension="pst" onPick={setPath} trigger={<Button className="shrink-0">{t("home.browse")}</Button>} />
                </div>
              )}
            </Field>
          </div>
          <Button type="submit" variant="primary" loading={add.isPending} disabled={!path.trim()}>
            {t("pst.add")}
          </Button>
        </form>
        <SendFile />
        {imports.isError ? <ErrorState title={t("pst.error")} onRetry={() => void imports.refetch()} /> : null}
        <ul className="flex flex-col gap-3">
          {items.map((item) => {
            const state = STATES[item.status] ?? { label: "pst.status.queued", tone: "waiting" as const };
            return (
              <li key={item.id} data-testid="pst-import" className="flex flex-col gap-2 rounded-md border border-line-subtle p-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="min-w-0 truncate text-md text-ink-primary">{item.name}</span>
                  <span className="flex shrink-0 items-center gap-2 text-sm text-ink-secondary">
                    <StatusDot tone={state.tone} />
                    {t(state.label)}
                  </span>
                </div>
                <Progress label={t("pst.progress", { name: item.name })} value={item.position} max={Math.max(item.total, 1)} />
                <p className="text-sm tabular-nums text-ink-muted">{t("pst.counts", { position: item.position, total: item.total, imported: item.imported, duplicates: item.duplicates })}</p>
                {item.error ? <p className="text-sm text-status-danger">{item.error}</p> : null}
                <div className="flex gap-2">
                  {item.status === "running" || item.status === "queued" ? <Button onClick={() => pause.mutate(item.id)}>{t("pst.pause")}</Button> : null}
                  {item.status === "paused" || item.status === "failed" ? <Button onClick={() => resume.mutate(item.id)}>{t(item.status === "failed" ? "pst.retry" : "pst.resume")}</Button> : null}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </Card>
  );
}
