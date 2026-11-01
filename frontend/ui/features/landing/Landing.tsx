"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useHomeStatus } from "@/ui/client/home";
import { Icon, type IconName } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { StageBar } from "@/ui/primitives/StageBar";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { t, type StringKey } from "@/ui/strings";

const ROWS: readonly { title: StringKey; detail: StringKey; completed: number; tone: "running" | "waiting" | "done" }[] = [
  { title: "landing.preview.row1.title", detail: "landing.preview.row1.detail", completed: 1, tone: "running" },
  { title: "landing.preview.row2.title", detail: "landing.preview.row2.detail", completed: 3, tone: "waiting" },
  { title: "landing.preview.row3.title", detail: "landing.preview.row3.detail", completed: 4, tone: "done" },
];

const PROMISES: readonly { icon: IconName; title: StringKey; detail: StringKey }[] = [
  { icon: "documents", title: "landing.promise.local.title", detail: "landing.promise.local.detail" },
  { icon: "approvals", title: "landing.promise.ask.title", detail: "landing.promise.ask.detail" },
  { icon: "logs", title: "landing.promise.see.title", detail: "landing.promise.see.detail" },
];

function ProductPreview() {
  return (
    <figure aria-label={t("landing.preview.label")} className="min-w-0 rounded-lg border border-line-subtle bg-surface-raised p-5 shadow-overlay">
      <figcaption className="mb-4 flex items-center justify-between gap-3">
        <span className="text-md font-medium text-ink-primary">{t("landing.preview.title")}</span>
        <span className="text-sm tabular-nums text-ink-muted">{t("landing.preview.count")}</span>
      </figcaption>
      <ul className="flex flex-col gap-4">
        {ROWS.map((row) => (
          <li key={row.title} className="flex items-center gap-3">
            <StatusDot tone={row.tone} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-md text-ink-primary">{t(row.title)}</p>
              <p className="truncate text-sm text-ink-muted">{t(row.detail)}</p>
            </div>
            <StageBar label={t(row.detail)} completed={row.completed} />
          </li>
        ))}
      </ul>
      <div className="mt-5 rounded-md border border-line-strong bg-surface-page p-4">
        <p className="text-sm text-ink-muted">{t("landing.preview.approval.label")}</p>
        <p className="mt-1 text-md text-ink-primary">{t("landing.preview.approval.text")}</p>
        <div aria-hidden className="mt-3 flex gap-2">
          <span className="rounded-md bg-accent-default px-3 py-1 text-sm text-accent-on">{t("landing.preview.approval.send")}</span>
          <span className="rounded-md border border-line-strong px-3 py-1 text-sm text-ink-secondary">{t("landing.preview.approval.edit")}</span>
        </div>
      </div>
    </figure>
  );
}

export function Landing() {
  const router = useRouter();
  const home = useHomeStatus();
  useEffect(() => {
    // Returning people never see this page.
    if (home.data && home.data.state !== "unset") router.replace("/");
  }, [home.data, router]);
  return (
    <div className="min-h-screen bg-surface-page text-ink-primary">
      <header className="mx-auto flex h-topbar max-w-page items-center px-6">
        <span className="text-lg font-medium">{t("app.name")}</span>
      </header>
      <main className="mx-auto grid max-w-page items-center gap-7 px-6 py-7 lg:grid-cols-2">
        <div className="flex flex-col items-start gap-5">
          <h1 className="font-serif text-hero leading-tight">{t("landing.headline")}</h1>
          <p className="max-w-popover text-lg text-ink-secondary">{t("landing.subhead")}</p>
          <Button variant="primary" onClick={() => router.push("/setup")}>
            {t("landing.start")}
          </Button>
        </div>
        <ProductPreview />
      </main>
      <section aria-label={t("landing.promise.label")} className="mx-auto grid max-w-page gap-5 px-6 pb-7 md:grid-cols-3">
        {PROMISES.map((promise) => (
          <div key={promise.title} className="flex gap-3">
            <Icon name={promise.icon} className="mt-1 h-4 w-4 shrink-0 text-ink-muted" />
            <div>
              <h2 className="text-md font-medium">{t(promise.title)}</h2>
              <p className="mt-1 text-md text-ink-muted">{t(promise.detail)}</p>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
