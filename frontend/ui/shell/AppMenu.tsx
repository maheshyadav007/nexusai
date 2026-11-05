"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { desktopApi } from "@/ui/client/desktop";
import { useProfile } from "@/ui/client/onboarding";
import { Avatar } from "@/ui/primitives/Avatar";
import { Button } from "@/ui/primitives/Button";
import { Menu, type MenuItem } from "@/ui/primitives/Menu";
import { useToast } from "@/ui/primitives/Toast";
import { Icon } from "@/ui/icons";
import { t } from "@/ui/strings";

export function AppMenu({ collapsed }: { collapsed: boolean }) {
  const router = useRouter(); const toast = useToast();
  const profile = useProfile();
  const name = profile.data?.name?.trim() || t("nav.userFallback");
  const label = t("nav.accountMenu", { name });
  const [desktop, setDesktop] = useState(false);
  useEffect(() => setDesktop(Boolean(desktopApi())), []);
  const run = (action: "restart" | "quit") => void desktopApi()?.action(action).catch(() => toast({ title: t("desktop.actionFailed") }));
  const closeTab = () => {
    window.close();
    // Browsers may only allow scripts to close tabs that a script opened.
    setTimeout(() => toast({ title: t("web.closeHint") }), 200);
  };
  const items: MenuItem[] = [
    { id: "settings", label: t("settings.title"), icon: "settings", onSelect: () => router.push("/settings") },
    { id: "about", label: t("desktop.about"), icon: "info", onSelect: () => router.push("/settings?section=about") },
    ...(desktop ? [
      { id: "restart", label: t("desktop.restart"), icon: "retry" as const, onSelect: () => run("restart") },
      { id: "quit", label: t("desktop.quit"), icon: "close" as const, onSelect: () => run("quit") },
    ] : [
      { id: "reload", label: t("web.reload"), icon: "retry" as const, onSelect: () => window.location.reload() },
      { id: "close", label: t("web.close"), icon: "close" as const, onSelect: closeTab },
    ]),
  ];
  return <Menu side="top" variant="account" label={label} items={items} trigger={
    <Button variant="quiet" data-testid="account-menu-trigger" className={`account-trigger w-full min-w-0 ${collapsed ? "justify-center px-0" : "justify-start px-2"}`} aria-label={label}>
      <span aria-hidden className="flex shrink-0"><Avatar name={name} size="md" /></span>
      {collapsed ? null : <><span className="min-w-0 flex-1 truncate text-left">{name}</span><Icon name="chevronDown" className="account-chevron shrink-0 rotate-180 text-ink-muted transition-transform duration-fast" /></>}
    </Button>
  } />;
}
