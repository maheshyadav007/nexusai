"use client";

import { copyText } from "@/ui/client/browser";
import { useState } from "react";
import { RecoverySettings } from "@/ui/features/home/RecoveryKey";
import { useHomeStatus, useResetEverything } from "@/ui/client/home";
import { useDiagnostics, useNetworkCheck } from "@/ui/client/system";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { Dialog } from "@/ui/primitives/Dialog";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { TextLink } from "@/ui/primitives/TextLink";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";

const gigabytes = (bytes: number) => new Intl.NumberFormat(undefined, { style: "unit", unit: "gigabyte", maximumFractionDigits: 0 }).format(bytes / 1024 ** 3);

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-3 text-md">
      <dt className="text-ink-secondary">{label}</dt>
      <dd className="min-w-0 break-all text-right tabular-nums text-ink-primary">{value}</dd>
    </div>
  );
}

export function HomeSettings() {
  const home = useHomeStatus();
  const diagnostics = useDiagnostics();
  return (
    <Card title={t("settings.section.home")} description={t("settings.home.description")}>
      <dl className="flex flex-col gap-2">
        <Row label={t("home.location")} value={home.data?.path ?? ""} />
        {diagnostics.data ? <Row label={t("settings.home.free")} value={gigabytes(diagnostics.data.free_bytes)} /> : null}
      </dl>
      <section aria-label={t("recovery.title")} className="mt-5 flex flex-col gap-3 border-t border-line-subtle pt-4">
        <h3 className="text-md font-medium text-ink-primary">{t("recovery.title")}</h3>
        <RecoverySettings />
      </section>
    </Card>
  );
}

export function NetworkSettings() {
  const toast = useToast();
  const diagnostics = useDiagnostics();
  const check = useNetworkCheck();
  const copy = (report: string) => void copyText(report).then(() => toast({ title: t("settings.network.copied") }));
  return (
    <Card title={t("settings.section.network")} description={t("settings.network.description")}>
      <div className="flex flex-col items-start gap-4">
        {diagnostics.isPending ? <Skeleton /> : null}
        {diagnostics.isError ? <ErrorState title={t("settings.network.error")} onRetry={() => void diagnostics.refetch()} /> : null}
        {diagnostics.data ? (
          <dl className="flex w-full flex-col gap-2">
            <Row label={t("settings.network.proxy")} value={diagnostics.data.proxy ?? t("settings.network.noProxy")} />
            <Row label={t("settings.network.system")} value={diagnostics.data.platform} />
            <Row label={t("settings.network.failed")} value={String(diagnostics.data.failed_events)} />
          </dl>
        ) : null}
        <div className="flex flex-wrap gap-3">
          <Button loading={check.isPending} onClick={() => check.mutate()}>
            {t("settings.network.check")}
          </Button>
          {diagnostics.data ? <Button onClick={() => copy(diagnostics.data.report)}>{t("settings.network.copy")}</Button> : null}
        </div>
        {check.isError ? <ErrorState title={t("settings.network.checkError")} /> : null}
        {check.data ? (
          <ul data-testid="network-results" className="flex w-full flex-col gap-2">
            {check.data.checks.map((item) => (
              <li key={item.name} className="flex items-center gap-2 text-md text-ink-secondary">
                <StatusDot tone={item.ok ? "done" : "failed"} />
                <span className="text-ink-primary">{item.name}</span>
                <span className="min-w-0 truncate text-sm text-ink-muted">{item.ok ? item.host : item.detail}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Card>
  );
}

/** It can't be undone, so it says what goes and asks for the word to be typed. */
export function ResetSettings() {
  const reset = useResetEverything();
  const [open, setOpen] = useState(false);
  const [word, setWord] = useState("");
  const [keepModels, setKeepModels] = useState(true);
  const required = t("reset.word");
  const run = () =>
    reset.mutate(
      { confirm: word, keep_models: keepModels },
      {
        onSuccess: () => {
          try {
            localStorage.clear();
          } catch {
            // Blocked storage has nothing in it to clear.
          }
          // A full reload, so nothing from before the reset is left in memory.
          window.location.assign("/");
        },
      },
    );
  return (
    <Card title={t("reset.title")} description={t("reset.description")}>
      <Dialog
        title={t("reset.dialog")}
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          setWord("");
        }}
        trigger={<Button variant="danger">{t("reset.open")}</Button>}
      >
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (word === required) run();
          }}
        >
          <div className="flex flex-col gap-1 text-md text-ink-secondary">
            <p className="text-ink-primary">{t("reset.gone")}</p>
            <ul className="flex list-disc flex-col gap-1 pl-5">
              <li>{t("reset.gone.mail")}</li>
              <li>{t("reset.gone.files")}</li>
              <li>{t("reset.gone.settings")}</li>
              <li>{t("reset.gone.signins")}</li>
            </ul>
            <p className="mt-2 text-sm text-ink-muted">{t("reset.stays")}</p>
          </div>
          <Checkbox checked={keepModels} onChange={setKeepModels} label={t("reset.keepModels")} />
          <Field label={t("reset.confirm", { word: required })}>{({ invalid, ...control }) => <Input autoComplete="off" spellCheck={false} invalid={invalid} value={word} onChange={(event) => setWord(event.target.value)} {...control} />}</Field>
          {reset.isError ? <ErrorState title={t("reset.failed")} /> : null}
          <div>
            <Button type="submit" variant="danger" loading={reset.isPending} disabled={word !== required}>{t("reset.action")}</Button>
          </div>
        </form>
      </Dialog>
    </Card>
  );
}

export function AboutSettings() {
  const diagnostics = useDiagnostics();
  return (
    <Card title={t("settings.section.about")} description={t("app.description")}>
      <dl className="flex flex-col gap-2">
        <Row label={t("settings.about.version")} value={diagnostics.data?.version ?? ""} />
      </dl>
      <p className="mt-4 text-md text-ink-secondary">{t("settings.about.what")}</p>
      <section aria-label={t("settings.about.team")} className="mt-4 flex flex-col gap-1">
        <h3 className="text-md font-medium text-ink-primary">{t("settings.about.team")}</h3>
        <p data-testid="team-member" className="text-md text-ink-secondary">{t("settings.about.member")}</p>
      </section>
    </Card>
  );
}
