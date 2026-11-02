"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useGetMoreFromFolder, useMailFolders } from "@/ui/client/mail";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { Icon } from "@/ui/icons";
import { ActiveMark } from "@/ui/primitives/Motion";
import { t } from "@/ui/strings";

// These have their own rows in the sidebar already, or are only how a server stores things.
const LISTED_ELSEWHERE = new Set(["inbox", "sent", "drafts", "archive", "trash", "all"]);

/** The folders on the server, including Gmail's labels. An email can be in several of them. */
export function FolderNav({ collapsed }: { collapsed: boolean }) {
  const folders = useMailFolders();
  const pathname = usePathname();
  const router = useRouter();
  const more = useGetMoreFromFolder();
  if (collapsed) return null;
  const rows = (folders.data?.folders ?? []).filter((row) => !LISTED_ELSEWHERE.has(row.role));
  if (!rows.length) return null;
  const depthOf = (name: string, parent?: string | null): number => {
    const above = rows.find((row) => row.name === parent);
    return above ? depthOf(above.name, above.parent) + 1 : 0;
  };
  return (
    <section aria-label={t("nav.folders")}>
      <ul className="flex flex-col gap-px">
        {rows.map((row) => {
          const href = `/mail/folder/${encodeURIComponent(row.name)}`;
          const active = pathname === href || pathname.startsWith(`${href}/`);
          const depth = depthOf(row.name, row.parent);
          return (
            <li key={row.name} data-testid="nav-folder">
              <ContextMenu items={[{ id: "open", label: t("menu.open"), onSelect: () => router.push(href) }, ...((row.on_server ?? 0) > (row.here ?? 0) ? [{ id: "rest", label: t("mail.folder.getRest"), onSelect: () => more.mutate({ folder: row.name }) }] : [])]}>
              <Link href={href} aria-current={active ? "page" : undefined} className={`focus-ring press relative flex items-center gap-2 rounded-md px-2 py-1 text-md transition-colors duration-fast ${active ? "text-ink-primary" : "text-ink-secondary hover:bg-surface-sunken hover:text-ink-primary"}`}>
                {active ? <ActiveMark group="nav-active" /> : null}
                <span aria-hidden className="relative flex shrink-0" {...{ style: { marginLeft: `${depth}rem` } }}>
                  <Icon name="folder" />
                </span>
                <span className="relative min-w-0 flex-1 truncate">{row.label}</span>
                {row.unread ? <span className="relative text-sm tabular-nums text-ink-muted">{row.unread}</span> : null}
              </Link>
              </ContextMenu>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
