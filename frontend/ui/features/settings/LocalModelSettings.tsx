"use client";

import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { IndexInfo } from "@/ui/client/contracts.generated";
import { useDateTime } from "@/ui/client/format";
import { useCancelModel, useChooseModel, useDetectModels, useDownloadModel, useImportModel, useRebuildIndex, useRemoveModel, useSaveSemantic, useSemantic } from "@/ui/client/semantic";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Input } from "@/ui/primitives/Input";
import { Progress } from "@/ui/primitives/Progress";
import { Select } from "@/ui/primitives/Select";
import { SettingRow } from "@/ui/primitives/SettingRow";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t, type StringKey } from "@/ui/strings";

const megabytes = (bytes: number) => new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(bytes / 1024 ** 2);
const percent = (done: number, total: number) => (total ? Math.min(100, Math.round((done / total) * 100)) : 0);
const gigabytes = (bytes: number) => new Intl.NumberFormat(undefined, { style: "unit", unit: "gigabyte", maximumFractionDigits: 0 }).format(bytes / 1024 ** 3);

const INDEX_NAME: Readonly<Record<IndexInfo["kind"], StringKey>> = { mail: "semantic.index.mail", document: "semantic.index.document" };
const INDEX_STATE: Readonly<Record<IndexInfo["state"], StringKey>> = {
  off: "semantic.index.off",
  current: "semantic.index.current",
  partial: "semantic.index.partial",
  out_of_date: "semantic.index.outOfDate",
};

/** Exactly what each index was built with, and a way to build it again when that's changed. */
function IndexVersions() {
  const semantic = useSemantic();
  const rebuild = useRebuildIndex();
  const format = useDateTime();
  return (
    <ul className="flex flex-col gap-3">
      {(semantic.data?.indexes ?? []).map((index) => {
        const settings = index.build_settings as { label?: string; revision?: string; chunk_chars?: number; overlap_chars?: number; most_chunks?: number; quantization?: string; extractor?: number };
        return (
          <li key={index.kind} data-testid={`index-${index.kind}`} className="flex flex-col gap-1 rounded-md border border-line-subtle p-3">
            <div className="flex items-center justify-between gap-3">
              <span className="text-md text-ink-primary">{t(INDEX_NAME[index.kind])}</span>
              <span className="text-sm text-ink-secondary">{t(INDEX_STATE[index.state])}</span>
            </div>
            <p className="text-sm tabular-nums text-ink-muted">{t("semantic.indexed", { done: index.indexed, total: index.total })}</p>
            <dl className="grid gap-x-3 text-sm tabular-nums text-ink-muted md:grid-cols-2">
              <div><dt className="inline">{t("semantic.version.model")} </dt><dd className="inline text-ink-secondary">{settings.label}</dd></div>
              <div><dt className="inline">{t("semantic.version.revision")} </dt><dd className="inline text-ink-secondary">{settings.revision?.slice(0, 8)}</dd></div>
              <div><dt className="inline">{t("semantic.version.chunks")} </dt><dd className="inline text-ink-secondary">{t("semantic.version.chunksValue", { size: settings.chunk_chars ?? 0, overlap: settings.overlap_chars ?? 0, most: settings.most_chunks ?? 0 })}</dd></div>
              <div><dt className="inline">{t("semantic.version.quantization")} </dt><dd className="inline text-ink-secondary">{settings.quantization}</dd></div>
              {settings.extractor ? <div><dt className="inline">{t("semantic.version.extractor")} </dt><dd className="inline text-ink-secondary">{settings.extractor}</dd></div> : null}
              {index.built ? <div><dt className="inline">{t("semantic.version.built")} </dt><dd className="inline text-ink-secondary">{format(index.built)}</dd></div> : null}
              <div><dt className="inline">{t("semantic.version.id")} </dt><dd className="inline break-all text-ink-secondary">{index.fingerprint}</dd></div>
            </dl>
            {index.state === "out_of_date" ? <p className="text-sm text-status-warning">{t("semantic.index.stale", { count: index.stale ?? 0 })}</p> : null}
            {index.state !== "off" ? <div className="pt-1"><Button loading={rebuild.isPending} onClick={() => rebuild.mutate(index.kind)}>{t("semantic.index.rebuild")}</Button></div> : null}
          </li>
        );
      })}
    </ul>
  );
}

/** Setup: what this computer has and suits, and the choice to download it or not. */
export function SearchModelChoice() {
  const semantic = useSemantic();
  const detection = useDetectModels();
  const choose = useChooseModel();
  const found = detection.data;
  const status = semantic.data;
  if (!found || !status) return <Skeleton className="h-6 w-full" />;
  const model = status.models.find((row) => row.active) ?? status.models[0];
  if (!model) return null;
  const reasons: Readonly<Record<typeof found.reason, StringKey>> = { already_here: "semantic.detect.alreadyHere", small_computer: "semantic.detect.small", best: "semantic.detect.best" };
  return (
    <div data-testid="search-choice" className="flex flex-col gap-3">
      <dl className="flex flex-col gap-1 rounded-md bg-surface-sunken p-3 text-sm text-ink-secondary">
        <div className="flex justify-between gap-3"><dt>{t("semantic.detect.memory")}</dt><dd className="tabular-nums">{gigabytes(found.memory_bytes)}</dd></div>
        <div className="flex justify-between gap-3"><dt>{t("semantic.detect.free")}</dt><dd className="tabular-nums">{gigabytes(found.free_bytes)}</dd></div>
        <div className="flex justify-between gap-3"><dt>{t("semantic.detect.source")}</dt><dd>{t(found.reachable ? "semantic.detect.reachable" : "semantic.detect.unreachable")}</dd></div>
      </dl>
      <p data-testid="search-recommendation" className="text-md text-ink-primary">{t(reasons[found.reason], { name: status.models.find((row) => row.id === found.recommended)?.label ?? "" })}</p>
      <SettingRow label={t("semantic.choose")} description={t("semantic.choose.note")} wide>
        <Select label={t("semantic.choose")} value={model.id} options={status.models.map((row) => ({ value: row.id, label: row.label }))} onChange={(id) => choose.mutate(id)} />
      </SettingRow>
      <p className="text-sm text-ink-muted">{t("semantic.skip.note")}</p>
    </div>
  );
}

/** Used in setup and in Settings, so the two can't drift apart. */
export function LocalModelSettings({ brief = false, bare = false }: { brief?: boolean; bare?: boolean }) {
  const semantic = useSemantic();
  const download = useDownloadModel();
  const cancel = useCancelModel();
  const remove = useRemoveModel();
  const choose = useChooseModel();
  const save = useSaveSemantic();
  const importFiles = useImportModel();
  const [mirror, setMirror] = useState<string | null>(null);
  const [folder, setFolder] = useState("");
  if (semantic.isPending) return <Card bare={bare} title={t("semantic.title")}><Skeleton className="h-6 w-full" /></Card>;
  if (semantic.isError) return <Card bare={bare} title={t("semantic.title")}><ErrorState title={t("semantic.error")} onRetry={() => void semantic.refetch()} /></Card>;
  const status = semantic.data;
  const model = status.models.find((row) => row.active) ?? status.models[0];
  if (!model) return null;
  const importFailed = importFiles.error instanceof ApiRequestError ? importFiles.error.detail.message : importFiles.isError ? t("semantic.import.failed") : null;
  return (
    <Card bare={bare} title={t("semantic.title")} description={bare ? undefined : t("semantic.description")}>
      <div className="flex flex-col gap-4" data-testid="local-model">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-md text-ink-primary">{model.label}</p>
            <p className="text-sm text-ink-muted">{model.description}</p>
          </div>
          {model.state === "ready" ? (
            <p className="text-sm text-status-success">{t("semantic.state.ready")}</p>
          ) : model.state === "downloading" ? (
            <Button onClick={() => cancel.mutate(model.id)}>{t("semantic.cancel")}</Button>
          ) : (
            <Button variant="primary" loading={download.isPending} onClick={() => download.mutate(model.id)}>
              {t(model.state === "failed" ? "semantic.retry" : "semantic.download", { size: megabytes(model.size_bytes) })}
            </Button>
          )}
        </div>
        {model.state === "downloading" ? (
          <div className="flex flex-col gap-1">
            <Progress label={t("semantic.downloading")} value={percent(model.downloaded_bytes ?? 0, model.size_bytes)} />
            <p className="text-sm tabular-nums text-ink-muted">{t("semantic.progress", { done: megabytes(model.downloaded_bytes ?? 0), total: megabytes(model.size_bytes) })}</p>
          </div>
        ) : null}
        {model.state === "failed" && model.error ? <p role="alert" className="text-sm text-status-danger">{model.error}</p> : null}
        {model.state === "ready" && (status.total ?? 0) > 0 ? (
          <div className="flex flex-col gap-1">
            <Progress label={t("semantic.indexing")} value={percent(status.indexed ?? 0, status.total ?? 0)} />
            <p className="text-sm tabular-nums text-ink-muted">{t("semantic.indexed", { done: status.indexed ?? 0, total: status.total ?? 0 })}</p>
          </div>
        ) : null}
        {brief ? null : <IndexVersions />}
        {brief && model.state !== "failed" ? null : (
          <ExpandRow label={t("semantic.more")} title={t("semantic.more")} defaultOpen={model.state === "failed"}>
            <SettingRow label={t("semantic.choose")} description={t("semantic.choose.note")}>
              <Select compact label={t("semantic.choose")} value={model.id} options={status.models.map((row) => ({ value: row.id, label: row.label }))} onChange={(id) => choose.mutate(id)} />
            </SettingRow>
            <form
              className="flex flex-col gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                save.mutate({ mirror: (mirror ?? status.mirror ?? "").trim() });
              }}
            >
              <label htmlFor="model-mirror" className="text-md text-ink-primary">{t("semantic.mirror")}</label>
              <p className="text-sm text-ink-muted">{t("semantic.mirror.note")}</p>
              <div className="flex gap-2">
                <Input id="model-mirror" value={mirror ?? status.mirror ?? ""} onChange={(event) => setMirror(event.target.value)} />
                <Button type="submit" className="shrink-0" loading={save.isPending}>{t("settings.save")}</Button>
              </div>
            </form>
            <form
              className="flex flex-col gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                importFiles.mutate({ id: model.id, folder: folder.trim() }, { onSuccess: () => setFolder("") });
              }}
            >
              <label htmlFor="model-folder" className="text-md text-ink-primary">{t("semantic.import")}</label>
              <p className="text-sm text-ink-muted">{t("semantic.import.note")}</p>
              <div className="flex gap-2">
                <Input id="model-folder" value={folder} onChange={(event) => setFolder(event.target.value)} />
                <Button type="submit" className="shrink-0" loading={importFiles.isPending} disabled={!folder.trim()}>{t("semantic.import.action")}</Button>
              </div>
              {importFailed ? <p role="alert" className="text-sm text-status-danger">{importFailed}</p> : null}
            </form>
            {model.state === "ready" ? (
              <div>
                <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate(model.id)}>{t("semantic.remove")}</Button>
              </div>
            ) : null}
          </ExpandRow>
        )}
      </div>
    </Card>
  );
}

/** For screens that search: what's true about meaning right now, in one line. */
export function MeaningNotice() {
  const semantic = useSemantic();
  const status = semantic.data;
  if (!status || status.ready) return null;
  const model = status.models.find((row) => row.active);
  if (model?.state === "downloading") {
    return (
      <div data-testid="meaning-notice" className="flex flex-col gap-1 rounded-md border border-line-subtle bg-surface-sunken px-3 py-2">
        <p className="text-sm text-ink-secondary">{t("semantic.notice.downloading")}</p>
        <Progress label={t("semantic.downloading")} value={percent(model.downloaded_bytes ?? 0, model.size_bytes)} />
      </div>
    );
  }
  return (
    <p data-testid="meaning-notice" className="rounded-md border border-line-subtle bg-surface-sunken px-3 py-2 text-sm text-ink-secondary">
      {t(model?.state === "failed" ? "semantic.notice.failed" : "semantic.notice.missing")}
    </p>
  );
}
