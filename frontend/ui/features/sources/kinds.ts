import type { SourceRef } from "@/ui/client/contracts.generated";
import type { IconName } from "@/ui/icons";

/** Anything that opens in the quick preview. A file in the Home folder may have no key yet, only its path. */
export interface PreviewSource {
  kind: SourceRef["kind"] | "file";
  ref: string;
  message?: number | null | undefined;
  page?: string | null | undefined;
  title?: string | undefined;
  detail?: string | undefined;
  date?: string | null | undefined;
  /** The matter a matter, task or reminder opens on, when it has one. */
  matter?: number | null | undefined;
}

export const mailSource = (thread: number, message?: number | null): PreviewSource => ({ kind: "mail", ref: String(thread), ...(message ? { message } : {}) });
export const documentSource = (key: string, page?: string | null): PreviewSource => ({ kind: "doc", ref: key, ...(page ? { page } : {}) });
export const fileSource = (path: string): PreviewSource => ({ kind: "file", ref: path });

export const sameSource = (a: PreviewSource, b: PreviewSource) => a.kind === b.kind && a.ref === b.ref;

export const SOURCE_ICONS: Record<PreviewSource["kind"], IconName> = { mail: "inbox", doc: "documents", file: "documents", matter: "today", task: "tasks", reminder: "reminders" };

/** The page each kind opens on in full. Every link to an email, a document or a matter is made here.
 * A task or reminder opens on its matter, or on its list when it has none. */
export function fullHref(source: PreviewSource): string {
  if (source.kind === "mail") return `/mail/all/${encodeURIComponent(source.ref)}`;
  if (source.kind === "doc") return `/documents/view?key=${encodeURIComponent(source.ref)}`;
  if (source.kind === "file") return `/documents/view?path=${encodeURIComponent(source.ref)}`;
  if (source.matter) return `/today?view=matters&matter=${source.matter}`;
  return source.kind === "reminder" ? "/planner/reminders" : "/planner/tasks";
}

/** The page number in a citation such as "p3", for viewers that can open on a page. */
export const pageNumber = (page: string | null | undefined): number | null => {
  const found = page ? /\d+/.exec(page) : null;
  return found ? Number(found[0]) : null;
};
