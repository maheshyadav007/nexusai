"use client";

import { useSessions } from "@/ui/client/sessions";
import { usePlannerCounts, useWaitingCount } from "@/ui/client/work";
import { CategoryNav } from "./CategoryNav";
import { FolderNav } from "./FolderNav";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useMailFolders } from "@/ui/client/mail";
import appConfig from "@/app.config.json";
import { Icon } from "@/ui/icons";
import { useSidebar } from "@/ui/client/settings";
import { AttentionCount } from "@/ui/primitives/AttentionCount";
import { IconButton } from "@/ui/primitives/IconButton";
import { ActiveMark, CountPop } from "@/ui/primitives/Motion";
import { ScrollArea } from "@/ui/primitives/ScrollArea";
import { Tooltip } from "@/ui/primitives/Tooltip";
import { t } from "@/ui/strings";
import { NAV_BOTTOM, NAV_SECTIONS, NAV_TOP, type NavItem } from "./nav";
import { SidebarEditor } from "./SidebarEditor";
import { arrange } from "./sidebarLayout";

// One highlight that glides to the row you chose.
const ACTIVE_ROW = "nav-active";
const MAIL_SECTION = "mail";
const FOLDERS_COME_BEFORE = new Set(["archive", "trash"]);

function NavRow({ item, active, collapsed, count, attention }: { item: NavItem; active: boolean; collapsed: boolean; count: number | undefined; attention: boolean }) {
  const label = t(item.label);
  const row = (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      {...(collapsed ? { "aria-label": label } : {})}
      className={`focus-ring press relative flex items-center gap-2 rounded-md px-2 py-1 text-md transition-colors duration-fast ${collapsed ? "justify-center" : ""} ${active ? "text-ink-primary" : "text-ink-secondary hover:bg-surface-raised hover:text-ink-primary"}`}
    >
      {active ? <ActiveMark group={ACTIVE_ROW} /> : null}
      <span className="relative flex min-w-0 flex-1 items-center gap-2">
        <Icon name={item.icon} />
        {collapsed ? null : <span className="min-w-0 flex-1 truncate">{label}</span>}
        {collapsed || !count ? null : attention ? <AttentionCount value={count} /> : <CountPop value={count} className="text-sm text-ink-muted" />}
      </span>
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

function useWaitingCounts(): Readonly<Record<string, number>> {
  const sessions = useSessions("");
  const decisions = useWaitingCount();
  const planner = usePlannerCounts();
  const waiting = (sessions.data?.sessions ?? []).filter((row) => row.status === "waiting").length;
  return { ...planner, ...(waiting ? { sessions: waiting } : {}), ...(decisions ? { today: decisions } : {}) };
}

/** Unread conversations in each fixed mail folder, the same as any other folder shows. */
function useUnreadCounts(): Readonly<Record<string, number>> {
  const folders = useMailFolders();
  const found = folders.data?.counts ?? {};
  return { priority: found.priority ?? 0, "all-mail": found.all ?? 0, sent: found.sent ?? 0, drafts: found.drafts ?? 0, archive: found.archive ?? 0, trash: found.trash ?? 0 };
}

export function NavSidebar({ counts }: { counts?: Readonly<Record<string, number>> }) {
  const pathname = usePathname();
  const waiting = useWaitingCounts();
  const unread = useUnreadCounts();
  const layout = useSidebar();
  const sections = arrange(NAV_SECTIONS, layout.data).filter((section) => !section.hidden);
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
        <NavRow item={item} active={active} collapsed={collapsed} count={(counts ?? { ...unread, ...waiting })[item.id]} attention={item.id in waiting} />
      </li>
    );
  };

  return (
    <nav aria-label={t("nav.label")} className={`flex h-full shrink-0 flex-col border-r border-line-subtle bg-surface-page ${collapsed ? "w-rail" : "w-sidebar"}`}>
      <div className={`flex h-topbar shrink-0 items-center px-3 ${collapsed ? "justify-center" : "justify-between"}`}>
        {collapsed ? null : <span className="text-lg font-medium text-ink-primary">{t("app.name")}</span>}
        <div className="flex items-center">
          {collapsed ? null : <SidebarEditor />}
          <IconButton icon={collapsed ? "expand" : "collapse"} label={t(collapsed ? "nav.expand" : "nav.collapse")} aria-expanded={!collapsed} onClick={toggle} />
        </div>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-5 px-2 pb-4">
          <ul className="flex flex-col gap-px">{NAV_TOP.map(row)}</ul>
          {sections.map((section) => {
            const items = section.items.filter((item) => !item.hidden);
            // Every folder and category sits together, before the two that end the list.
            const closing = items.findIndex((item) => FOLDERS_COME_BEFORE.has(item.id));
            const split = section.id === MAIL_SECTION ? (closing < 0 ? items.length : closing) : items.length;
            return (
              <section key={section.id} aria-label={t(section.label)}>
                {collapsed || !section.heading ? null : <h2 className="mb-1 px-2 text-sm text-ink-muted">{t(section.label)}</h2>}
                <ul className="flex flex-col gap-px">{items.slice(0, split).map(row)}</ul>
                {section.id === MAIL_SECTION ? <CategoryNav collapsed={collapsed} /> : null}
                {section.id === MAIL_SECTION ? <FolderNav collapsed={collapsed} /> : null}
                <ul className="flex flex-col gap-px">{items.slice(split).map(row)}</ul>
              </section>
            );
          })}
        </div>
      </ScrollArea>
      <ul className="flex shrink-0 flex-col gap-px border-t border-line-subtle p-2">{NAV_BOTTOM.map(row)}</ul>
    </nav>
  );
}
