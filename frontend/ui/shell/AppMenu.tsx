"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { desktopApi } from "@/ui/client/desktop";
import { Button } from "@/ui/primitives/Button";
import { Menu, type MenuItem } from "@/ui/primitives/Menu";
import { useToast } from "@/ui/primitives/Toast";
import { Icon } from "@/ui/icons";
import { t } from "@/ui/strings";

export function AppMenu({ collapsed }: { collapsed: boolean }) {
  const router = useRouter(); const toast = useToast();
  const [desktop, setDesktop] = useState(false);
  useEffect(() => setDesktop(Boolean(desktopApi())), []);
  const run = (action: "restart" | "quit") => void desktopApi()?.action(action).catch(() => toast({ title: t("desktop.actionFailed") }));
  const items: MenuItem[] = [
    { id: "settings", label: t("settings.title"), icon: "settings", onSelect: () => router.push("/settings") },
    { id: "about", label: t("desktop.about"), icon: "info", onSelect: () => router.push("/settings?section=about") },
    ...(desktop ? [
      { id: "restart", label: t("desktop.restart"), icon: "retry" as const, onSelect: () => run("restart") },
      { id: "quit", label: t("desktop.quit"), icon: "close" as const, onSelect: () => run("quit") },
    ] : []),
  ];
  return <Menu side="top" items={items} trigger={<Button variant="quiet" className="w-full justify-start" aria-label={t("settings.title")}><Icon name="settings" />{collapsed ? null : t("settings.title")}</Button>} />;
}
