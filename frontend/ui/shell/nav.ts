import type { IconName } from "@/ui/icons";
import type { StringKey } from "@/ui/strings";
import nav from "./nav.json";

export interface NavItem {
  id: string;
  label: StringKey;
  icon: IconName;
  href: string;
  /** Says when a screen that isn't built yet will arrive. */
  arrives?: StringKey;
}

export interface NavSection {
  id: string;
  label: StringKey;
  items: NavItem[];
}

interface RawItem {
  id: string;
  labelKey: string;
  icon: string;
  href: string;
  arrivesKey?: string;
}

const item = (raw: RawItem, sectionArrives?: string): NavItem => {
  const arrives = raw.arrivesKey ?? sectionArrives;
  return { id: raw.id, label: raw.labelKey as StringKey, icon: raw.icon as IconName, href: raw.href, ...(arrives ? { arrives: arrives as StringKey } : {}) };
};

export const NAV_TOP: NavItem[] = nav.top.map((raw) => item(raw));
export const NAV_SECTIONS: NavSection[] = nav.sections.map((section) => ({
  id: section.id,
  label: section.labelKey as StringKey,
  items: section.items.map((raw) => item(raw, section.arrivesKey)),
}));
export const NAV_BOTTOM: NavItem[] = nav.bottom.map((raw) => item(raw));

const ALL = [...NAV_TOP, ...NAV_SECTIONS.flatMap((section) => section.items), ...NAV_BOTTOM];

export const findNavItem = (pathname: string): NavItem | undefined => ALL.find((entry) => pathname === entry.href || pathname.startsWith(`${entry.href}/`));
