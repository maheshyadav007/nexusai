"use client";

import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { useCancelModel, useChooseModel, useDownloadModel, useImportModel, useRemoveModel, useSaveSemantic, useSemantic } from "@/ui/client/semantic";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Input } from "@/ui/primitives/Input";
import { Progress } from "@/ui/primitives/Progress";
import { Select } from "@/ui/primitives/Select";
import { SettingRow } from "@/ui/primitives/SettingRow";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Switch } from "@/ui/primitives/Switch";
import { t } from "@/ui/strings";

const megabytes = (bytes: number) => new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(bytes / 1024 ** 2);
const percent = (done: number, total: number) => (total ? Math.min(100, Math.round((done / total) * 100)) : 0);

/** Used in setup and in Settings, so the two can't drift apart. */
export function LocalModelSettings({ brief = false }: { brief?: boolean }) {
  const semantic = useSemantic();
  const download = useDownloadModel();
  const cancel = useCancelModel();
  const remove = useRemoveModel();
  const choose = useChooseModel();
  const save = useSaveSemantic();
  const importFiles = useImportModel();
  const [mirror, setMirror] = useState<string | null>(null);
  const [folder, setFolder] = useState("");
  if (semantic.isPending) return <Card title={t("semantic.title")}><Skeleton className="h-6 w-full" /></Card>;
  if (semantic.isError) return <Card title={t("semantic.title")}><ErrorState title={t("semantic.error")} onRetry={() => void semantic.refetch()} /></Card>;
  const status = semantic.data;
  const model = status.models.find((row) => row.active) ?? status.models[0];
  if (!model) return null;
  const importFailed = importFiles.error instanceof ApiRequestError ? importFiles.error.detail.message : importFiles.isError ? t("semantic.import.failed") : null;
  return (
    <Card title={t("semantic.title")} description={t("semantic.description")}>
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
        {brief && model.state !== "failed" ? null : (
          <ExpandRow label={t("semantic.more")} title={t("semantic.more")} defaultOpen={model.state === "failed"}>
            <SettingRow label={t("semantic.choose")} description={t("semantic.choose.note")}>
              <Select compact label={t("semantic.choose")} value={model.id} options={status.models.map((row) => ({ value: row.id, label: row.label }))} onChange={(id) => choose.mutate(id)} />
            </SettingRow>
            <SettingRow label={t("semantic.auto")} description={t("semantic.auto.note")}>
              <div className="flex justify-end">
                <Switch label={t("semantic.auto")} hideLabel checked={status.auto_download ?? true} onChange={(auto_download) => save.mutate({ auto_download })} />
              </div>
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
