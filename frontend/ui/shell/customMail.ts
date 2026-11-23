import type { MailCategory, MailFolder } from "@/ui/client/contracts.generated";

export const CUSTOM_MAIL_PREVIEW = 5;
// Each home shows its biggest few folders; the rest are under Show all.
export const HOME_PREVIEW = 3;
const LISTED_ELSEWHERE = new Set(["inbox", "sent", "drafts", "archive", "trash", "all"]);
// Kept from the AI's catch-all, and where invitations go, named as the server names them.
export const AUTOMATED = "Automated";
export const CALENDAR = "Calendar";

/** A folder the AI skips. A folder takes its side from its home, so this is set on every
 *  folder in Kept from the AI. */
export const keptFromAi = (item: MailCategory) => item.ai_reads === false || item.name === AUTOMATED || item.name === CALENDAR;

/** Filed by senders on both sides, waiting to be split on the Sort page. */
export const partlyKept = (item: MailCategory) => !keptFromAi(item) && (item.senders_read ?? 0) > 0 && (item.senders_kept ?? 0) > 0;

export const categoryHref = (name: string) => `/mail/category/${encodeURIComponent(name)}`;
export const folderHref = (name: string) => `/mail/folder/${encodeURIComponent(name)}`;
export const isCurrentMail = (pathname: string, href: string) => pathname === href || pathname.startsWith(`${href}/`);

/** The person's folders, as the sidebar lists them. Automated, the catch-all of Kept from the
 *  AI, isn't one: its mail is simply kept. An empty folder shows when someone made it, or when
 *  there's something in a folder under it. */
export const customCategories = (categories: readonly MailCategory[]) => {
  const listed = categories.filter((item) => !item.proposed && item.name !== AUTOMATED);
  const holding = new Set<string>();
  for (const item of listed) if ((item.count ?? 0) > 0) for (let at: MailCategory | undefined = item; at; at = listed.find((up) => up.name === at?.parent)) {
    if (holding.has(at.name)) break;
    holding.add(at.name);
  }
  // Calendar is made by sorting, so it waits until an invitation is in it.
  return listed.filter((item) => holding.has(item.name) || (item.source === "user" && item.name !== CALENDAR));
};

/** One folder in its home, with how deep it sits and what's under it. */
export interface TreeRow {
  item: MailCategory;
  depth: number;
  children: number;
  /** Its unread conversations and every folder's under it, as opening it shows them. */
  unread: number;
  /** Its conversations and every folder's under it. */
  count: number;
}

/** Each home's folders as a tree: the top ones biggest first, each followed by what's inside
 *  it. `open` names the folders unfolded; the rest keep what's inside them folded. */
export function folderTree(categories: readonly MailCategory[], kept: boolean, open: ReadonlySet<string> | "all" = "all"): TreeRow[] {
  const rows = customCategories(categories).filter((item) => keptFromAi(item) === kept);
  const names = new Set(rows.map((item) => item.name));
  const below = new Map<string, MailCategory[]>();
  for (const item of rows) {
    const parent = item.parent && names.has(item.parent) ? item.parent : "";
    below.set(parent, [...(below.get(parent) ?? []), item]);
  }
  const totals = new Map<string, { unread: number; count: number }>();
  const total = (item: MailCategory, seen: Set<string>): { unread: number; count: number } => {
    const known = totals.get(item.name);
    if (known) return known;
    const sum = { unread: item.unread ?? 0, count: item.count ?? 0 };
    for (const child of below.get(item.name) ?? []) {
      if (seen.has(child.name)) continue;
      const inner = total(child, new Set([...seen, child.name]));
      sum.unread += inner.unread;
      sum.count += inner.count;
    }
    totals.set(item.name, sum);
    return sum;
  };
  const out: TreeRow[] = [];
  const visit = (parent: string, depth: number, seen: Set<string>) => {
    const level = [...(below.get(parent) ?? [])];
    // The top of a home is biggest first; inside a folder, in the person's order.
    if (!parent) level.sort((a, b) => total(b, new Set([b.name])).count - total(a, new Set([a.name])).count);
    for (const item of level) {
      if (seen.has(item.name)) continue;
      const children = (below.get(item.name) ?? []).length;
      out.push({ item, depth, children, ...total(item, new Set([item.name])) });
      if (children && (open === "all" || open.has(item.name))) visit(item.name, depth + 1, new Set([...seen, item.name]));
    }
  };
  visit("", 0, new Set());
  return out;
}

/** The folders above one, nearest first, so the open one is never folded away. */
export function ancestors(categories: readonly MailCategory[], name: string): string[] {
  const out: string[] = [];
  for (let at = categories.find((item) => item.name === name)?.parent; at && !out.includes(at); at = categories.find((item) => item.name === at)?.parent) out.push(at);
  return out;
}

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
