"use client";

import { useEffect, useState } from "react";
import { desktopApi, type DesktopStatus } from "@/ui/client/desktop";
import { Button } from "@/ui/primitives/Button";
import { Progress } from "@/ui/primitives/Progress";
import { t } from "@/ui/strings";

export function DesktopUpdates() {
  const [status, setStatus] = useState<DesktopStatus | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const api = desktopApi();
    if (!api) return;
    let active = true;
    const read = () => void api.status().then(value => { if (active) setStatus(value); }).catch(() => {});
    read(); const timer = setInterval(read, 1000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  if (!status) return null;
  const act = (action: "check" | "download" | "install") => {
    setError(""); void desktopApi()?.action(action).then(setStatus).catch(() => setError(t("desktop.updateFailed")));
  };
  return <section className="mt-4 flex flex-col gap-3 border-t border-line-subtle pt-4" aria-label={t("desktop.updates")}>
    <p className="text-md text-ink-secondary">{t("desktop.version", { version: status.version })}</p>
    <p role="status" className="text-sm text-ink-muted">{t(!status.configured ? "desktop.unconfigured" : `desktop.update.${status.state}`)}</p>
    {status.availableVersion ? <p className="text-sm">{t("desktop.available", { version: status.availableVersion })}</p> : null}
    {status.state === "downloading" ? <Progress label={t("desktop.downloading")} value={status.percent} /> : null}
    {status.error || error ? <p role="alert" className="text-sm text-status-danger">{status.error || error}</p> : null}
    <div><Button disabled={!status.configured || status.state === "checking" || status.state === "downloading" || status.state === "installing"} onClick={() => act(status.state === "ready" ? "install" : status.state === "available" ? "download" : "check")}>{t(status.state === "ready" ? "desktop.install" : status.state === "available" ? "desktop.download" : "desktop.check")}</Button></div>
  </section>;
}
