"use client";

import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useCategories, useMailFolders } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Tooltip } from "@/ui/primitives/Tooltip";
import { t } from "@/ui/strings";
import { ancestors, CALENDAR, categoryHref, folderTree, HOME_PREVIEW, isCurrentMail, partlyKept, type TreeRow } from "./customMail";
import { FolderLink } from "./FolderLink";
import { useHiddenFolders, useShownFolders } from "./hiddenFolders";
import { MailNavMenu } from "./MailNavMenu";
import { useRememberedFold } from "./SidebarFold";

export const HOME_HREF = { reads: "/mail/inbox", kept: "/mail/kept" } as const;
type Side = keyof typeof HOME_HREF;

/** One of the two homes: Read by AI, everything the AI reads, or Hidden from AI, everything it
 *  never sees. An open eye or a closed one says which, on the home and on every folder in it.
 *  It shows the folders ticked on the Sort page (or its biggest few), the rest wait under Show
 *  all. Either home folds; Hidden from AI starts folded. A folder opens with its own mail and
 *  everything under it, and counts it all. */
export function HomeNav({ side, collapsed }: { side: Side; collapsed: boolean }) {
  const categories = useCategories();
  const folders = useMailFolders();
  const pathname = usePathname();
  const { hidden } = useHiddenFolders();
  const { chosen } = useShownFolders();
  const [all, setAll] = useState(false);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const items = categories.data?.categories ?? [];
  const kept = side === "kept";
  const href = HOME_HREF[side];
  const label = t(kept ? "nav.home.kept" : "nav.home.inbox");
  const unread = folders.data?.counts?.[side] ?? 0;
  // The open folder is never folded away, or hidden under Show all, or inside a folded home.
  const current = items.find((item) => isCurrentMail(pathname, categoryHref(item.name)));
  const insideHome = Boolean(current && (current.ai_reads === false) === kept && !isCurrentMail(pathname, href));
  const home = useRememberedFold(`home-${side}`, !kept, insideHome);
  const link = (
    <FolderLink
      href={href}
      icon={kept ? "keptFromAi" : "readByAi"}
      tone={kept ? "kept" : "ai"}
      label={collapsed ? "" : label}
      unread={collapsed ? 0 : unread}
      active={isCurrentMail(pathname, href)}
      detail={t(kept ? "nav.home.kept.about" : "nav.home.inbox.about")}
      {...(collapsed ? {} : { fold: home })}
      menu={(row) => <MailNavMenu href={href} scope={{ folder: side }} home={side}>{row}</MailNavMenu>}
    />
  );
  if (collapsed) return <Tooltip content={label} side="right"><div data-testid={`nav-home-${side}`}>{link}</div></Tooltip>;
  const holding = current ? ancestors(items, current.name) : [];
  const unfolded = new Set([...open, ...holding]);
  // Calendar has a place of its own in Hidden from AI, never ranked with the rest.
  const rows = folderTree(items, kept, unfolded).filter((row) => row.item.name !== CALENDAR);
  const top = rows.filter((row) => row.depth === 0);
  const biggest = Math.max(1, ...top.map((row) => row.count));
  const rootOf = (row: TreeRow) => [row.item.name, ...ancestors(items, row.item.name)].at(-1) as string;
  const preview = (chosen ? top : top.slice(0, HOME_PREVIEW))
    .filter((row) => !hidden.has(row.item.name))
    .map((row) => row.item.name);
  const opened = current ? rootOf({ item: current, depth: 0, children: 0, unread: 0, count: 0 }) : null;
  const folded = new Set([...preview, ...(opened ? [opened] : [])]);
  const shownTop = all ? new Set(top.map((row) => row.item.name)) : folded;
  const shown = rows.filter((row) => shownTop.has(rootOf(row)));
  const calendar = items.find((item) => item.name === CALENDAR);
  const toggle = (name: string) => setOpen(() => {
    const next = new Set(unfolded);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    return next;
  });
  return (
    <section aria-label={t("nav.home.section", { name: label })} data-testid={`nav-home-${side}`} className="flex flex-col gap-px">
      {link}
      {home.open ? <>
        <ul className="flex flex-col gap-px">
          {shown.map(({ item, depth, children, unread: within, count }) => {
            const to = categoryHref(item.name);
            return (
              <li key={item.name} data-testid="nav-category">
                <FolderLink
                  href={to}
                  icon={kept ? "keptFromAi" : item.mode === "exact" ? "folderRule" : "folderSmart"}
                  tone={kept ? "kept" : partlyKept(item) ? "partly" : "ai"}
                  label={item.name}
                  unread={within}
                  {...(depth === 0 ? { size: count / biggest } : {})}
                  active={isCurrentMail(pathname, to)}
                  depth={depth + 1}
                  detail={[t(item.mode === "exact" ? "categories.kind.exact" : "categories.kind.smart"), ...(partlyKept(item) ? [t("nav.folder.mixed")] : [])].join(". ")}
                  {...(children ? { fold: { open: unfolded.has(item.name), toggle: () => toggle(item.name) } } : {})}
                  menu={(row) => <MailNavMenu href={to} scope={{ folder: "all", category: item.name }} category={item}>{row}</MailNavMenu>}
                />
              </li>
            );
          })}
          {kept ? (
            <li data-testid="nav-calendar">
              <FolderLink
                href={categoryHref(CALENDAR)}
                icon="calendar"
                tone="kept"
                label={t("nav.calendar")}
                unread={calendar?.unread ?? 0}
                active={isCurrentMail(pathname, categoryHref(CALENDAR))}
                depth={1}
                detail={t("nav.calendar.about")}
                {...(calendar ? { menu: (row: ReactNode) => <MailNavMenu href={categoryHref(CALENDAR)} scope={{ folder: "all", category: CALENDAR }} category={calendar}>{row}</MailNavMenu> } : {})}
              />
            </li>
          ) : null}
        </ul>
        {/* Only when Show all would show more than the home shows anyway. */}
        {top.some((row) => !folded.has(row.item.name)) ? (
          <Button variant="quiet" aria-expanded={all} className="ml-5 self-start px-2 py-1 text-sm" onClick={() => setAll(!all)}>
            {t(all ? "nav.folders.showLess" : "nav.folders.showAll", { count: top.length })}
          </Button>
        ) : null}
      </> : null}
    </section>
  );
}
