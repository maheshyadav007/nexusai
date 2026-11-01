"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import appConfig from "@/app.config.json";
import { Icon } from "@/ui/icons";
import { IconButton } from "@/ui/primitives/IconButton";
import { ScrollArea } from "@/ui/primitives/ScrollArea";
import { Tooltip } from "@/ui/primitives/Tooltip";
import { t } from "@/ui/strings";
import { NAV_BOTTOM, NAV_SECTIONS, NAV_TOP, type NavItem } from "./nav";

function NavRow({ item, active, collapsed, count }: { item: NavItem; active: boolean; collapsed: boolean; count: number | undefined }) {
  const label = t(item.label);
  const row = (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      {...(collapsed ? { "aria-label": label } : {})}
      className={`focus-ring flex items-center gap-2 rounded-md px-2 py-1 text-md transition-colors duration-fast ${collapsed ? "justify-center" : ""} ${active ? "bg-surface-sunken font-medium text-ink-primary" : "text-ink-secondary hover:bg-surface-sunken hover:text-ink-primary"}`}
    >
      <Icon name={item.icon} />
      {collapsed ? null : <span className="min-w-0 flex-1 truncate">{label}</span>}
      {collapsed || !count ? null : <span className="text-sm tabular-nums text-ink-muted">{count}</span>}
    </Link>
  );
  return collapsed ? (
    <Tooltip content={label} side="right">
      {row}
    </Tooltip>
  ) : (
    row
  );
}

export function NavSidebar({ counts = {} }: { counts?: Readonly<Record<string, number>> }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(appConfig.storageKeys.sidebar) === "collapsed");
    } catch {
      // Storage can be blocked; the sidebar then starts open.
    }
  }, []);

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(appConfig.storageKeys.sidebar, next ? "collapsed" : "open");
    } catch {
      // Storage can be blocked; the choice then lasts until reload.
    }
  };

  const row = (item: NavItem) => {
    const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
    return (
      <li key={item.id}>
        <NavRow item={item} active={active} collapsed={collapsed} count={counts[item.id]} />
      </li>
    );
  };

  return (
    <nav aria-label={t("nav.label")} className={`flex h-full shrink-0 flex-col border-r border-line-subtle bg-surface-page ${collapsed ? "w-rail" : "w-sidebar"}`}>
      <div className={`flex h-topbar shrink-0 items-center px-3 ${collapsed ? "justify-center" : "justify-between"}`}>
        {collapsed ? null : <span className="text-lg font-medium text-ink-primary">{t("app.name")}</span>}
        <IconButton icon={collapsed ? "expand" : "collapse"} label={t(collapsed ? "nav.expand" : "nav.collapse")} aria-expanded={!collapsed} onClick={toggle} />
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-5 px-2 pb-4">
          <ul className="flex flex-col gap-px">{NAV_TOP.map(row)}</ul>
          {NAV_SECTIONS.map((section) => (
            <section key={section.id} aria-label={t(section.label)}>
              {collapsed ? null : <h2 className="mb-1 px-2 text-sm text-ink-muted">{t(section.label)}</h2>}
              <ul className="flex flex-col gap-px">{section.items.map(row)}</ul>
            </section>
          ))}
        </div>
      </ScrollArea>
      <ul className="flex shrink-0 flex-col gap-px border-t border-line-subtle p-2">{NAV_BOTTOM.map(row)}</ul>
    </nav>
  );
}
