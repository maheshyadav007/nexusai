"use client";

import { RecoverySettings } from "@/ui/features/home/RecoveryKey";
import { useHomeStatus } from "@/ui/client/home";
import { useDiagnostics, useNetworkCheck } from "@/ui/client/system";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
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
  const copy = (report: string) => void navigator.clipboard.writeText(report).then(() => toast({ title: t("settings.network.copied") }));
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

export function AboutSettings() {
  const diagnostics = useDiagnostics();
  return (
    <Card title={t("settings.section.about")} description={t("app.description")}>
      <dl className="flex flex-col gap-2">
        <Row label={t("settings.about.version")} value={diagnostics.data?.version ?? ""} />
      </dl>
      <p className="mt-4 text-md text-ink-muted">{t("settings.about.credit")}</p>
      <p className="mt-2 text-md">
        <TextLink href="https://github.com/heydamir/unslop" target="_blank" rel="noreferrer">
          {t("settings.about.unslop")}
        </TextLink>
      </p>
    </Card>
  );
}
