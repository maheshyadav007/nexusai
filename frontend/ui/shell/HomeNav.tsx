"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";
import { useCategories, useMailFolders } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Tooltip } from "@/ui/primitives/Tooltip";
import { t } from "@/ui/strings";
import { ancestors, categoryHref, folderTree, HOME_PREVIEW, isCurrentMail, partlyKept, type TreeRow } from "./customMail";
import { FolderLink } from "./FolderLink";
import { useHiddenFolders } from "./hiddenFolders";
import { MailNavMenu } from "./MailNavMenu";

export const HOME_HREF = { reads: "/mail/inbox", kept: "/mail/kept" } as const;
type Side = keyof typeof HOME_HREF;

/** One of the two homes: Inbox, everything the AI reads, or Kept from the AI, everything it
 *  doesn't. Its biggest few folders follow it as a tree, and the rest wait under Show all. A
 *  folder opens with its own mail and everything under it, and counts it all. */
export function HomeNav({ side, collapsed }: { side: Side; collapsed: boolean }) {
  const categories = useCategories();
  const folders = useMailFolders();
  const pathname = usePathname();
  const { hidden } = useHiddenFolders();
  const [all, setAll] = useState(false);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const items = categories.data?.categories ?? [];
  const kept = side === "kept";
  const href = HOME_HREF[side];
  const label = t(kept ? "nav.home.kept" : "nav.home.inbox");
  const unread = folders.data?.counts?.[side] ?? 0;
  const home = (
    <FolderLink
      href={href}
      icon={kept ? "keptFromAi" : "inbox"}
      tone={kept ? "kept" : "ai"}
      label={collapsed ? "" : label}
      unread={collapsed ? 0 : unread}
      active={isCurrentMail(pathname, href)}
      detail={t(kept ? "nav.home.kept.about" : "nav.home.inbox.about")}
      menu={(link) => <MailNavMenu href={href} scope={{ folder: side }} home={side}>{link}</MailNavMenu>}
    />
  );
  if (collapsed) return <Tooltip content={label} side="right"><div data-testid={`nav-home-${side}`}>{home}</div></Tooltip>;
  // The open folder is never folded away, or hidden under Show all.
  const current = items.find((item) => isCurrentMail(pathname, categoryHref(item.name)));
  const holding = current ? ancestors(items, current.name) : [];
  const unfolded = new Set([...open, ...holding]);
  const rows = folderTree(items, kept, unfolded);
  const top = rows.filter((row) => row.depth === 0);
  const rootOf = (row: TreeRow) => [row.item.name, ...ancestors(items, row.item.name)].at(-1) as string;
  const preview = top.filter((row) => !hidden.has(row.item.name)).slice(0, HOME_PREVIEW).map((row) => row.item.name);
  const opened = current ? rootOf({ item: current, depth: 0, children: 0, unread: 0, count: 0 }) : null;
  const shownTop = new Set(all ? top.map((row) => row.item.name) : [...preview, ...(opened ? [opened] : [])]);
  const shown = rows.filter((row) => shownTop.has(rootOf(row)));
  const toggle = (name: string) => setOpen(() => {
    const next = new Set(unfolded);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    return next;
  });
  return (
    <section aria-label={t("nav.home.section", { name: label })} data-testid={`nav-home-${side}`} className="flex flex-col gap-px">
      {home}
      <ul className="flex flex-col gap-px">
        {shown.map(({ item, depth, children, unread: within }) => {
          const link = categoryHref(item.name);
          return (
            <li key={item.name} data-testid="nav-category">
              <FolderLink
                href={link}
                icon={item.mode === "exact" ? "folderRule" : "folderSmart"}
                tone={kept ? "kept" : partlyKept(item) ? "partly" : "ai"}
                label={item.name}
                unread={within}
                active={isCurrentMail(pathname, link)}
                depth={depth + 1}
                detail={[t(item.mode === "exact" ? "categories.kind.exact" : "categories.kind.smart"), ...(partlyKept(item) ? [t("nav.folder.mixed")] : [])].join(". ")}
                {...(children ? { fold: { open: unfolded.has(item.name), toggle: () => toggle(item.name) } } : {})}
                menu={(row) => <MailNavMenu href={link} scope={{ folder: "all", category: item.name }} category={item}>{row}</MailNavMenu>}
              />
            </li>
          );
        })}
      </ul>
      {top.length > HOME_PREVIEW || shownTop.size < top.length ? (
        <Button variant="quiet" aria-expanded={all} className="ml-5 self-start px-2 py-1 text-sm" onClick={() => setAll(!all)}>
          {t(all ? "nav.folders.showLess" : "nav.folders.showAll", { count: top.length })}
        </Button>
      ) : null}
    </section>
  );
}
