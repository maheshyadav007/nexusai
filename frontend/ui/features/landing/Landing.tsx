"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useHomeStatus } from "@/ui/client/home";
import { Icon, type IconName } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { Rise } from "@/ui/primitives/Motion";
import { t, type StringKey } from "@/ui/strings";

const PROMISES: readonly { icon: IconName; title: StringKey; detail: StringKey }[] = [
  { icon: "documents", title: "landing.promise.local.title", detail: "landing.promise.local.detail" },
  { icon: "search", title: "landing.promise.find.title", detail: "landing.promise.find.detail" },
  { icon: "approvals", title: "landing.promise.ask.title", detail: "landing.promise.ask.detail" },
  { icon: "logs", title: "landing.promise.see.title", detail: "landing.promise.see.detail" },
];

/** The real shape of the app's chat, played through once: a question, the work, then a decision. */
function ProductPreview() {
  return (
    <figure aria-label={t("landing.preview.label")} className="flex min-w-0 flex-col gap-3 rounded-lg border border-line-subtle bg-surface-raised p-5 shadow-overlay">
      <Rise className="self-end rounded-lg bg-surface-sunken px-3 py-2 text-md text-ink-primary">{t("landing.preview.ask")}</Rise>
      <Rise delay={1} className="flex items-center gap-2 text-sm text-ink-muted">
        <Icon name="thinking" className="h-4 w-4 shrink-0" />
        {t("landing.preview.trace")}
      </Rise>
      <Rise delay={2} className="text-md text-ink-primary">{t("landing.preview.answer")}</Rise>
      <Rise delay={3} className="rounded-md border border-line-strong bg-surface-page p-4">
        <p className="text-sm text-ink-muted">{t("landing.preview.approval.label")}</p>
        <p className="mt-1 text-md text-ink-primary">{t("landing.preview.approval.text")}</p>
        <div aria-hidden className="mt-3 flex gap-2">
          <span className="rounded-md bg-accent-default px-3 py-1 text-sm text-accent-on">{t("landing.preview.approval.send")}</span>
          <span className="rounded-md border border-line-strong px-3 py-1 text-sm text-ink-secondary">{t("landing.preview.approval.edit")}</span>
        </div>
      </Rise>
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
          <h1 className="text-balance font-serif text-hero leading-tight">{t("landing.headline")}</h1>
          <p className="max-w-popover text-lg text-ink-secondary">{t("landing.subhead")}</p>
          <div className="flex flex-col items-start gap-2">
            <Button variant="primary" onClick={() => router.push("/setup")}>
              {t("landing.start")}
            </Button>
            <p className="text-sm text-ink-muted">{t("setup.time")}</p>
          </div>
        </div>
        <ProductPreview />
      </main>
      <section aria-label={t("landing.promise.label")} className="mx-auto grid max-w-page gap-5 px-6 pb-7 md:grid-cols-2 lg:grid-cols-4">
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
