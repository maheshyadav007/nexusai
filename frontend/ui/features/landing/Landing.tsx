"use client";

import { PostyGuide } from "@/ui/shell/PostyGuide";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useHomeStatus } from "@/ui/client/home";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { Rise } from "@/ui/primitives/Motion";
import { t } from "@/ui/strings";

/** The real shape of the app's chat, played through once: a question, the work, then a decision. */
function ProductPreview() {
  return (
    <figure aria-label={t("landing.preview.label")} className="flex w-full min-w-0 flex-col gap-3 rounded-lg border border-line-subtle bg-surface-raised p-5 shadow-overlay">
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
    <div className="min-h-screen bg-surface-page text-ink-primary lg:flex lg:h-screen lg:flex-col lg:overflow-hidden">
      <header className="mx-auto flex h-topbar max-w-page items-center px-6">
        <span className="text-lg font-medium">{t("app.name")}</span>
      </header>
      <main className="mx-auto grid w-full max-w-page flex-1 items-stretch px-6 py-7 lg:min-h-0 lg:grid-cols-5">
        <div className="relative flex min-h-drawer flex-col items-start justify-center py-5 lg:col-span-2 lg:pr-7">
          <PostyGuide prominent title={t("landing.headline")} message="posty.welcome" />
          <div className="flex flex-col items-start gap-2">
            <Button variant="primary" onClick={() => router.push("/setup")}>
              {t("landing.start")}
            </Button>
            <p className="text-sm text-ink-muted">{t("setup.time")}</p>
          </div>
          <span aria-hidden className="absolute right-0 top-1/2 hidden h-popover w-px -translate-y-1/2 bg-line-subtle lg:block" />
        </div>
        <div className="flex min-w-0 items-center py-5 lg:col-span-3 lg:pl-7"><ProductPreview /></div>
      </main>
    </div>
  );
}
