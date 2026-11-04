"use client";

import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { useChooseHome, useCurrentFolder, useHomeCheck } from "@/ui/client/home";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { t } from "@/ui/strings";
import { FolderPicker } from "./FolderPicker";

function formatBytes(bytes: number): string {
  return new Intl.NumberFormat(undefined, { style: "unit", unit: "gigabyte", maximumFractionDigits: 0 }).format(bytes / 1024 ** 3);
}

/** Picks a folder, shows live checks, and opens it. mustExist is for finding a Home that moved. */
export function HomeChooser({ initialPath, mustExist = false, action, onChosen }: { initialPath: string; mustExist?: boolean; action: string; onChosen?: () => void }) {
  const [path, setPath] = useState(initialPath);
  const check = useHomeCheck(path);
  const choose = useChooseHome();
  const current = useCurrentFolder();
  const result = check.data?.path && !check.isFetching ? check.data : undefined;
  const missingHome = mustExist && result && !result.is_existing_home;
  const problem = result?.problems[0] ?? (missingHome ? t("home.notAHome") : undefined);
  return (
    <div className="flex flex-col items-start gap-4">
      <div className="w-full">
        <Field label={t("home.location")} {...(problem ? { error: problem } : {})}>
          {({ invalid, ...control }) => (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Input invalid={invalid} spellCheck={false} value={path} onChange={(event) => setPath(event.target.value)} {...control} />
              <div className="flex gap-2">
                <FolderPicker start={path} onPick={setPath} trigger={<Button className="shrink-0">{t("home.browse")}</Button>} />
                <Button className="shrink-0" data-testid="use-current-folder" loading={current.isPending} onClick={() => current.mutate(undefined, { onSuccess: (found) => setPath(found.path) })}>{t("home.useCurrent")}</Button>
              </div>
            </div>
          )}
        </Field>
      </div>
      {result?.warnings.map((warning) => (
        <p key={warning} className="text-md text-status-warning">
          {warning}
        </p>
      ))}
      {result?.free_bytes != null && result.ok ? <p className="text-md tabular-nums text-ink-muted">{t("home.free", { size: formatBytes(result.free_bytes) })}</p> : null}
      {result?.is_existing_home && !mustExist ? <p className="text-md text-ink-secondary">{t("home.existing")}</p> : null}
      {choose.isError ? <ErrorState title={t("home.failed")} description={choose.error instanceof ApiRequestError ? choose.error.detail.message : t("settings.models.error")} /> : null}
      <Button
        variant="primary"
        loading={choose.isPending}
        disabled={!result?.ok || Boolean(missingHome)}
        onClick={() =>
          choose.mutate({ path, must_exist: mustExist }, onChosen ? { onSuccess: onChosen } : {})
        }
      >
        {action}
      </Button>
    </div>
  );
}
