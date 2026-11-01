"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { useDateTime } from "@/ui/client/format";
import { useBackups, useHomeStatus, useRestoreBackup, useUnlockHome } from "@/ui/client/home";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";
import { HomeChooser } from "./HomeChooser";

const RECOVERABLE = new Set(["missing", "locked", "damaged"]);

function UnlockForm() {
  const unlock = useUnlockHome();
  const [key, setKey] = useState("");
  const refused = unlock.error instanceof ApiRequestError ? unlock.error.detail.message : null;
  return (
    <form
      className="flex flex-col items-start gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        unlock.mutate({ recovery_key: key });
      }}
    >
      <div className="w-full">
        <Field label={t("recovery.enter")} {...(refused ? { error: refused } : {})}>
          {({ invalid, ...control }) => <Input className="font-mono" autoComplete="off" spellCheck={false} invalid={invalid} value={key} onChange={(event) => setKey(event.target.value)} {...control} />}
        </Field>
      </div>
      <Button type="submit" variant="primary" loading={unlock.isPending} disabled={!key.trim()}>
        {t("recovery.open")}
      </Button>
    </form>
  );
}

function RestoreList() {
  const backups = useBackups(true);
  const restore = useRestoreBackup();
  const format = useDateTime();
  const rows = backups.data?.backups ?? [];
  return (
    <div className="flex flex-col gap-3">
      {backups.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {backups.isError ? <ErrorState title={t("backups.error")} onRetry={() => void backups.refetch()} /> : null}
      {backups.isSuccess && !rows.length ? <p className="text-md text-ink-secondary">{t("backups.none")}</p> : null}
      {rows.length ? <p className="text-md text-ink-secondary">{t("backups.description")}</p> : null}
      <ul className="flex flex-col gap-2">
        {rows.map((row) => (
          <li key={row.name} data-testid="backup" className="flex items-center justify-between gap-3 rounded-md border border-line-subtle p-3">
            <span className="text-md tabular-nums text-ink-primary">{format(row.time)}</span>
            <Button loading={restore.isPending} onClick={() => restore.mutate({ name: row.name })}>
              {t("backups.restore")}
            </Button>
          </li>
        ))}
      </ul>
      {restore.isError ? <ErrorState title={t("backups.restoreFailed")} /> : null}
    </div>
  );
}

export function HomeRecovery() {
  const router = useRouter();
  const home = useHomeStatus();
  const [choosingNew, setChoosingNew] = useState(false);
  useEffect(() => {
    if (home.data && !RECOVERABLE.has(home.data.state)) router.replace("/");
  }, [home.data, router]);
  const data = home.data;
  return (
    <main className="mx-auto flex min-h-screen max-w-dialog flex-col justify-center gap-5 p-6 text-ink-primary">
      <h1 className="font-serif text-display">{t("recover.title")}</h1>
      {!data || !RECOVERABLE.has(data.state) ? <Skeleton className="h-6 w-full" /> : null}
      {data?.state === "locked" || data?.state === "damaged" ? (
        <>
          <p className="text-md text-ink-secondary">{data.message}</p>
          <p className="break-all rounded-md bg-surface-sunken p-3 font-mono text-sm text-ink-secondary">{data.path}</p>
          {data.state === "locked" ? <UnlockForm /> : <RestoreList />}
        </>
      ) : null}
      {data?.state !== "missing" ? null : (
        <>
          <p className="text-md text-ink-secondary">{data.message}</p>
          <p className="break-all rounded-md bg-surface-sunken p-3 font-mono text-sm text-ink-secondary">{data.path}</p>
          {choosingNew ? (
            <>
              <p className="text-md text-ink-secondary">{t("recover.new.description")}</p>
              <HomeChooser key="new" initialPath={data.default_path} action={t("recover.new.action")} onChosen={() => router.replace("/")} />
              <Button variant="quiet" onClick={() => setChoosingNew(false)}>
                {t("recover.locate.back")}
              </Button>
            </>
          ) : (
            <>
              <p className="text-md text-ink-secondary">{t("recover.locate.description")}</p>
              <HomeChooser key="locate" initialPath={data.path ?? data.default_path} mustExist action={t("recover.locate.action")} onChosen={() => router.replace("/")} />
              <Button variant="quiet" onClick={() => setChoosingNew(true)}>
                {t("recover.new.switch")}
              </Button>
            </>
          )}
        </>
      )}
    </main>
  );
}
