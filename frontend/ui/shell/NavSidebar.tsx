"use client";

import { useSessions } from "@/ui/client/sessions";
import { useCockpit, usePlannerCounts, useWaitingCount } from "@/ui/client/work";
import { MailNavMenu } from "./MailNavMenu";
import type { MailCategory, MarkFolderRead } from "@/ui/client/contracts.generated";
import { FolderNav, SpamNav } from "./FolderNav";
import { HomeNav } from "./HomeNav";
import { SidebarFold } from "./SidebarFold";
import { customFolders, folderHref, isCurrentMail, spamFolders } from "./customMail";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useId, useState, type ReactNode } from "react";
import { useCategories, useDrafts, useMailFolders } from "@/ui/client/mail";
import appConfig from "@/app.config.json";
import { Icon } from "@/ui/icons";
import { useSidebar } from "@/ui/client/settings";
import { AttentionCount } from "@/ui/primitives/AttentionCount";
import { Button } from "@/ui/primitives/Button";
import { IconButton } from "@/ui/primitives/IconButton";
import { ActiveMark, CountPop } from "@/ui/primitives/Motion";
import { Tooltip } from "@/ui/primitives/Tooltip";
import { t, tn } from "@/ui/strings";
import { NAV_BOTTOM, NAV_SECTIONS, NAV_TOP, type NavItem } from "./nav";
import { AppMenu } from "./AppMenu";
import { SidebarEditor } from "./SidebarEditor";
import { arrange } from "./sidebarLayout";

// One highlight that glides to the row you chose.
const ACTIVE_ROW = "nav-active";
const MAIL_SECTION = "mail";
const PRIORITY = "priority";

function NavRow({ item, active, collapsed, count, attention }: { item: NavItem; active: boolean; collapsed: boolean; count: number | undefined; attention: boolean }) {
  const label = t(item.label);
  const home = item.id === "today";
  // The link is named by its label alone ("Tasks", not "Tasks 1"); the number is described.
  const countId = useId();
  const counted = !collapsed && Boolean(count);
  const row = (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      {...(collapsed ? { "aria-label": label } : {})}
      {...(counted ? { "aria-describedby": countId } : {})}
      className={`focus-ring press relative flex items-center gap-2 rounded-md px-2 transition-colors duration-fast ${home ? "border border-accent-default/20 bg-accent-default/5 py-2 text-lg font-medium text-ink-primary hover:bg-accent-default/10" : "py-px text-md"} ${collapsed ? "justify-center" : ""} ${active ? "text-ink-primary" : home ? "" : "text-ink-secondary hover:bg-surface-raised hover:text-ink-primary"}`}
    >
      {active ? <ActiveMark group={ACTIVE_ROW} {...(home ? { className: "absolute inset-0 rounded-md bg-accent-default/10" } : {})} /> : null}
      <span className="relative flex min-w-0 flex-1 items-center gap-2">
        <Icon name={item.icon} {...(home ? { className: "text-accent-default" } : {})} />
        {collapsed ? null : <span className="min-w-0 flex-1 truncate">{label}</span>}
        {counted && count ? (
          <>
            <span aria-hidden>{attention ? <AttentionCount value={count} /> : <CountPop value={count} className="text-sm text-ink-muted" />}</span>
            {/* Hidden, so it isn't part of the link's name, yet still read as its description. */}
            <span id={countId} hidden>{t(attention ? "nav.count.attention" : "nav.count.quiet", { count })}</span>
          </>
        ) : null}
      </span>
    </Link>
  );
  const mailRow = item.href.startsWith("/mail/") ? <MailNavMenu href={item.href} scope={{ folder: (item.id === "all-mail" ? "all" : item.id) as MarkFolderRead["folder"] }}>{row}</MailNavMenu> : row;
  return collapsed ? (
    <Tooltip content={label} side="right">
      <span className="block">{mailRow}</span>
    </Tooltip>
  ) : (
    mailRow
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
  return { priority: found.priority ?? 0, important: found.important ?? 0, starred: found.starred ?? 0, "all-mail": found.all ?? 0, sent: found.sent ?? 0, drafts: found.drafts ?? 0, archive: found.archive ?? 0, trash: found.trash ?? 0 };
}

/** The system folders, needed now and then: Important, All mail, Archive, Spam and Trash, and
 *  the labels and folders of the mail account itself. Those come from the server, have no rules
 *  and can hold mail from both sides, so they sit here rather than in a home. */
function MoreNav({ items, row }: { items: NavItem[]; row: (item: NavItem) => React.ReactNode }) {
  const pathname = usePathname();
  const folders = useMailFolders();
  const categories = useCategories();
  const spam = spamFolders(folders.data?.folders ?? [], pathname);
  const labels = customFolders(folders.data?.folders ?? [], pathname, categories.data?.categories ?? []);
  if (!items.length && !spam.length && !labels.length) return null;
  const holdsActive = items.some((item) => isCurrentMail(pathname, item.href)) || [...spam, ...labels].some((folder) => isCurrentMail(pathname, folderHref(folder.name)));
  return (
    <SidebarFold id="more" label={t("nav.more")} remember={false} holdsActive={holdsActive}>
      <ul className="flex flex-col gap-px">{items.map(row)}</ul>
      <SpamNav />
      {labels.length ? <div className="mt-2 flex flex-col gap-1"><h3 className="px-2 text-sm text-ink-muted">{t("nav.labels")}</h3><FolderNav collapsed={false} /></div> : null}
    </SidebarFold>
  );
}

/** Mail's rows with the two homes right after Priority: one tree of folders under each. */
function withHomes(items: readonly NavItem[], row: (item: NavItem) => React.ReactNode, collapsed: boolean) {
  const homes = (["reads", "kept"] as const).map((side) => <li key={`home-${side}`} className={collapsed ? "" : "mt-1"}><HomeNav side={side} collapsed={collapsed} /></li>);
  const at = items.findIndex((item) => item.id === PRIORITY);
  if (at < 0) return [...homes, ...items.map(row)];
  return [...items.slice(0, at + 1).map(row), ...homes, <li key="homes-end" aria-hidden className="h-1" />, ...items.slice(at + 1).map(row)];
}

// Whether the sidebar is the narrow rail, for what's put into it from outside the shell.
const Collapsed = createContext(false);
export const useSidebarCollapsed = () => useContext(Collapsed);

export function NavSidebar({ counts, setup }: { counts?: Readonly<Record<string, number>>; setup?: ReactNode }) {
  const pathname = usePathname();
  const waiting = useWaitingCounts();
  const unread = useUnreadCounts();
  const drafts = useDrafts();
  const draftCount = (drafts.data?.drafts.length ?? 0) + (unread.drafts ?? 0);
  const layout = useSidebar();
  const sections = arrange(NAV_SECTIONS, layout.data).filter((section) => !section.hidden);
  const [collapsed, setCollapsed] = useState(false);
  const tools = NAV_BOTTOM.filter((item) => item.id !== "settings");
  // Something of the app's own needs fixing: Tools says so, as Today does.
  const problem = (useCockpit().data?.health ?? []).some((item) => item.state === "problem");

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
      <div className={`flex h-7 shrink-0 items-center px-3 ${collapsed ? "justify-center" : "justify-between"}`}>
        {collapsed ? null : <span className="text-lg font-medium text-ink-primary">{t("app.name")}</span>}
        <div className="flex items-center">
          {collapsed ? null : <SidebarEditor />}
          <IconButton icon={collapsed ? "expand" : "collapse"} label={t(collapsed ? "nav.expand" : "nav.collapse")} aria-expanded={!collapsed} onClick={toggle} />
        </div>
      </div>
      <ul className="flex shrink-0 flex-col gap-px px-2 pb-4 pt-2">{NAV_TOP.map(row)}<Collapsed.Provider value={collapsed}>{setup}</Collapsed.Provider></ul>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain category-scroll">
        <div className="flex min-h-full flex-col gap-2 px-2 pb-2">
          {sections.map((section) => {
            const items = section.items.filter((item) => !item.hidden);
            const mail = section.id === MAIL_SECTION;
            // Mail keeps the daily folders in view. Drafts shows only when there are some, and
            // the rarely needed ones wait under More, except in the narrow rail.
            const daily = mail ? items.filter((item) => (collapsed || !item.more) && (item.id !== "drafts" || draftCount > 0 || isCurrentMail(pathname, item.href))) : items;
            return (
              <section key={section.id} aria-label={t(section.label)} className={mail ? "flex shrink-0 flex-col gap-1" : "shrink-0 border-t border-line-subtle pt-2"}>
                {collapsed || !section.heading ? null : <h2 className="mb-1 px-2 text-sm text-ink-muted">{t(section.label)}</h2>}
                <ul className="flex flex-col gap-px">{mail ? withHomes(daily, row, collapsed) : daily.map(row)}</ul>
                {mail && !collapsed ? <div className="mt-2 flex flex-col gap-3"><MoreNav items={items.filter((item) => item.more)} row={row} /></div> : null}
              </section>
            );
          })}
          {/* Little used, so they have a section of their own that stays folded; the narrow rail
              still shows each icon. */}
          <section aria-label={t("nav.tools")} className="shrink-0 border-t border-line-subtle pt-2">
            {collapsed ? <ul className="flex flex-col gap-px">{tools.map(row)}</ul> : <SidebarFold id="tools" label={t("nav.tools")} actions={problem ? <span role="img" aria-label={t("nav.tools.problem")} data-testid="tools-problem" className="mr-2 h-2 w-2 rounded-full bg-status-danger" /> : null} holdsActive={tools.some((item) => isCurrentMail(pathname, item.href))}><ul className="flex flex-col gap-px">{tools.map(row)}</ul></SidebarFold>}
          </section>
        </div>
      </div>
      <div className="shrink-0 border-t border-line-subtle p-2">
        <AppMenu collapsed={collapsed} />
      </div>
    </nav>
  );
}
