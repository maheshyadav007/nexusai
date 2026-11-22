import type { MailCategory, MailFolder } from "@/ui/client/contracts.generated";

export const CUSTOM_MAIL_PREVIEW = 5;
const LISTED_ELSEWHERE = new Set(["inbox", "sent", "drafts", "archive", "trash", "all"]);
// The folders the AI skips that the Sort step files into, named as the server names them.
export const AUTOMATED = "Automated";
export const CALENDAR = "Calendar";

/** A folder the AI skips: Automated, Calendar and what's filed under them, one set that way, or
 *  one whose every conversation a sorting rule keeps from the AI. Sorting decides by sender, so
 *  a folder that also holds mail the AI reads stays with the person's folders. */
export const keptFromAi = (item: MailCategory) =>
  item.ai_reads === false || [AUTOMATED, CALENDAR].some((name) => item.name === name || item.name.startsWith(`${name}/`)) || ((item.count ?? 0) > 0 && (item.kept ?? 0) >= (item.count ?? 0));

/** Some of it kept from the AI by sorting rules, and some read. */
export const partlyKept = (item: MailCategory) => !keptFromAi(item) && (item.kept ?? 0) > 0;

export const categoryHref = (name: string) => `/mail/category/${encodeURIComponent(name)}`;
export const folderHref = (name: string) => `/mail/folder/${encodeURIComponent(name)}`;
export const isCurrentMail = (pathname: string, href: string) => pathname === href || pathname.startsWith(`${href}/`);

export const customCategories = (categories: readonly MailCategory[]) => categories.filter((item) => !item.proposed && (item.count ?? 0) > 0);

const holdsMail = (row: MailFolder, pathname: string) => (row.here ?? 0) > 0 || (row.on_server ?? 0) > 0 || isCurrentMail(pathname, folderHref(row.name));

/** The server's folders and Gmail's labels that are the person's own: not the fixed ones, not
 * Spam, and not Gmail's Starred and Important, which the app's views of those names stand for. A
 * label named like one of the person's folders shows once, as that folder. */
export const customFolders = (folders: readonly MailFolder[], pathname: string, categories: readonly MailCategory[] = []) => {
  const taken = new Set(categories.map((item) => item.name.toLocaleLowerCase()));
  return folders.filter((row) => !LISTED_ELSEWHERE.has(row.role) && row.role !== "junk" && !row.shown_elsewhere && !taken.has(row.name.toLocaleLowerCase()) && holdsMail(row, pathname));
};

/** Spam, which waits under More with the other system folders. */
export const spamFolders = (folders: readonly MailFolder[], pathname: string) => folders.filter((row) => row.role === "junk" && holdsMail(row, pathname));

/** Keep the open folder reachable without growing the five-row preview. */
export function previewMailHrefs(hrefs: readonly string[], pathname: string): Set<string> {
  const preview = hrefs.slice(0, CUSTOM_MAIL_PREVIEW);
  const active = hrefs.find((href) => isCurrentMail(pathname, href));
  if (active && !preview.includes(active)) preview[preview.length - 1] = active;
  return new Set(preview);
}
