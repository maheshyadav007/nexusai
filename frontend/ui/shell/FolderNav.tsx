"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";
import type { MailFolder } from "@/ui/client/contracts.generated";
import { useCategories, useMailFolders } from "@/ui/client/mail";
import { FolderLink } from "./FolderLink";
import { MailNavMenu } from "./MailNavMenu";
import { Button } from "@/ui/primitives/Button";
import { t } from "@/ui/strings";
import { CUSTOM_MAIL_PREVIEW, customFolders, folderHref, isCurrentMail, previewMailHrefs, spamFolders } from "./customMail";

/** Rows in reading order: each folder, then what's inside it, unless it's folded. */
function walk(rows: readonly MailFolder[], open: ReadonlySet<string>): { row: MailFolder; depth: number; children: boolean }[] {
  const names = new Set(rows.map((row) => row.name));
  const below = new Map<string, MailFolder[]>();
  for (const row of rows) {
    const parent = row.parent && names.has(row.parent) ? row.parent : "";
    below.set(parent, [...(below.get(parent) ?? []), row]);
  }
  const out: { row: MailFolder; depth: number; children: boolean }[] = [];
  const visit = (parent: string, depth: number, seen: Set<string>) => {
    for (const row of below.get(parent) ?? []) {
      if (seen.has(row.name)) continue;
      const children = (below.get(row.name) ?? []).length > 0;
      out.push({ row, depth, children });
      if (children && open.has(row.name)) visit(row.name, depth + 1, new Set([...seen, row.name]));
    }
  };
  visit("", 0, new Set());
  return out;
}

function FolderRows({ rows }: { rows: readonly MailFolder[] }) {
  const pathname = usePathname();
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  // The open folder is never hidden inside a folded one.
  const holding = new Set<string>();
  for (const row of rows) {
    if (!isCurrentMail(pathname, folderHref(row.name))) continue;
    for (let above = row.parent; above && !holding.has(above); above = rows.find((item) => item.name === above)?.parent) holding.add(above);
  }
  const shown = new Set([...open, ...holding]);
  const toggle = (name: string) => setOpen(() => {
    const next = new Set(shown);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    return next;
  });
  return (
    <ul className="flex flex-col gap-px">
      {walk(rows, shown).map(({ row, depth, children }) => {
        const href = folderHref(row.name);
        const junk = row.role === "junk";
        return (
          <li key={row.name} data-testid="nav-folder">
            <FolderLink
              href={href}
              icon={junk ? "error" : "label"}
              tone={junk ? "kept" : "label"}
              label={junk ? t("nav.junk") : row.label}
              unread={row.unread ?? 0}
              active={isCurrentMail(pathname, href)}
              depth={depth}
              {...(children ? { fold: { open: shown.has(row.name), toggle: () => toggle(row.name) } } : {})}
              menu={(link) => <MailNavMenu href={href} scope={{ location: row.name }} {...((row.on_server ?? 0) > (row.here ?? 0) ? { moreFolder: row.name } : {})}>{link}</MailNavMenu>}
              />
          </li>
        );
      })}
    </ul>
  );
}

/** The person's folders and labels on the server, nested, each folder folding what's inside it.
 * An email can be in several of them. */
export function FolderNav({ collapsed }: { collapsed: boolean }) {
  const folders = useMailFolders();
  const categories = useCategories();
  const pathname = usePathname();
  const [all, setAll] = useState(false);
  if (collapsed) return null;
  const rows = customFolders(folders.data?.folders ?? [], pathname, categories.data?.categories ?? []);
  if (!rows.length) return null;
  const names = new Set(rows.map((row) => row.name));
  const top = rows.filter((row) => !row.parent || !names.has(row.parent));
  // The first few at the top, and the one open; what's inside them comes along.
  const kept = new Set(previewMailHrefs(top.map((row) => folderHref(row.name)), pathname));
  const rootOf = (row: MailFolder): string => {
    const seen = new Set([row.name]);
    let at = row;
    for (let above = rows.find((item) => item.name === at.parent); above && !seen.has(above.name); above = rows.find((item) => item.name === at.parent)) {
      seen.add(above.name);
      at = above;
    }
    return at.name;
  };
  const shown = all ? rows : rows.filter((row) => kept.has(folderHref(rootOf(row))));
  return (
    <section aria-label={t("nav.folders")} className="flex flex-col">
      <FolderRows rows={shown} />
      {top.length > CUSTOM_MAIL_PREVIEW ? <Button variant="quiet" aria-expanded={all} className="self-start px-2 py-1 text-sm" onClick={() => setAll(!all)}>{t(all ? "nav.folders.showLess" : "nav.folders.showAll", { count: top.length })}</Button> : null}
    </section>
  );
}

/** Spam, among the system folders under More. */
export function SpamNav() {
  const folders = useMailFolders();
  const pathname = usePathname();
  const rows = spamFolders(folders.data?.folders ?? [], pathname);
  return rows.length ? <FolderRows rows={rows} /> : null;
}
