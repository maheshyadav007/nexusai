"use client";

import { useEffect, useState } from "react";
import { desktopApi } from "@/ui/client/desktop";
import { Icon } from "@/ui/icons";
import { t } from "@/ui/strings";

/** Windows draws its own caption buttons over the reserved right-hand area. */
export function DesktopFrame() {
  const [desktop, setDesktop] = useState(false);
  useEffect(() => {
    if (desktopApi()?.platform !== "win32") return;
    setDesktop(true);
    document.documentElement.dataset.desktop = "true";
    return () => { delete document.documentElement.dataset.desktop; };
  }, []);
  useEffect(() => {
    if (!desktop) return;
    const update = () => { const caption = document.querySelector(".desktop-caption"); if (!caption) return; const colors = getComputedStyle(caption); void desktopApi()?.caption({ color: colors.backgroundColor, symbolColor: colors.color }).catch(() => {}); };
    update(); const observer = new MutationObserver(update); observer.observe(document.documentElement, { attributes: true });
    return () => observer.disconnect();
  }, [desktop]);
  if (!desktop) return null;
  return <header className="desktop-caption"><Icon name="agent" className="h-4 w-4" /><span>{t("app.name")}</span><span className="text-ink-muted">{t("desktop.beta")}</span><div id="nexus-window-tools" className="desktop-tools flex min-w-0 flex-1 items-center justify-between gap-3" /></header>;
}
