import type { MailCategory, MailFolder } from "@/ui/client/contracts.generated";

export const CUSTOM_MAIL_PREVIEW = 5;
const LISTED_ELSEWHERE = new Set(["inbox", "sent", "drafts", "archive", "trash", "all"]);

export const categoryHref = (name: string) => `/mail/category/${encodeURIComponent(name)}`;
export const folderHref = (name: string) => `/mail/folder/${encodeURIComponent(name)}`;
export const isCurrentMail = (pathname: string, href: string) => pathname === href || pathname.startsWith(`${href}/`);

export const customCategories = (categories: readonly MailCategory[]) => categories.filter((item) => !item.proposed && (item.count ?? 0) > 0);

export const customFolders = (folders: readonly MailFolder[], pathname: string) => folders.filter((row) =>
  !LISTED_ELSEWHERE.has(row.role) && ((row.here ?? 0) > 0 || (row.on_server ?? 0) > 0 || isCurrentMail(pathname, folderHref(row.name))),
);

/** Keep the open folder reachable without growing the five-row preview. */
export function previewMailHrefs(hrefs: readonly string[], pathname: string): Set<string> {
  const preview = hrefs.slice(0, CUSTOM_MAIL_PREVIEW);
  const active = hrefs.find((href) => isCurrentMail(pathname, href));
  if (active && !preview.includes(active)) preview[preview.length - 1] = active;
  return new Set(preview);
}
