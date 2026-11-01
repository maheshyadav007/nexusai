"use client";

import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { useAddPst, usePausePst, usePstImports, useResumePst } from "@/ui/client/documents";
import { useHomeStatus } from "@/ui/client/home";
import { FolderPicker } from "@/ui/features/home/FolderPicker";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
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
        <form
          className="flex flex-col items-start gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            add.mutate(path.trim(), { onSuccess: () => setPath("") });
          }}
        >
          <div className="w-full">
            <Field label={t("pst.file")} {...(add.isError ? { error: add.error instanceof ApiRequestError ? add.error.detail.message : t("pst.addFailed") } : {})}>
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
