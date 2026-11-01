import type { SidebarLayout } from "@/ui/client/contracts.generated";
import type { NavItem, NavSection } from "./nav";

function ordered<T extends { id: string }>(entries: readonly T[], order: readonly string[] = []): T[] {
  const byId = new Map(entries.map((entry) => [entry.id, entry]));
  const placed = order.flatMap((id) => byId.get(id) ?? []);
  // Anything new in an app update joins at the end, so a saved layout never hides it.
  return [...placed, ...entries.filter((entry) => !order.includes(entry.id))];
}

export interface ArrangedSection extends NavSection {
  hidden: boolean;
  items: (NavItem & { hidden: boolean })[];
}

/** The sidebar in the person's chosen order, with hidden entries marked. */
export function arrange(sections: readonly NavSection[], layout: SidebarLayout | undefined): ArrangedSection[] {
  const hidden = new Set(layout?.hidden ?? []);
  return ordered(sections, layout?.sections ?? []).map((section) => ({
    ...section,
    hidden: hidden.has(section.id),
    items: ordered(section.items, layout?.items?.[section.id] ?? []).map((item) => ({ ...item, hidden: hidden.has(item.id) })),
  }));
}
