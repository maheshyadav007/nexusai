"use client";

import { useSidebar, useUpdateSidebar } from "@/ui/client/settings";
import type { SidebarLayout } from "@/ui/client/contracts.generated";

// A folder left out of the sidebar is kept with the rest of its layout, under this name.
const idOf = (name: string) => `folder:${name}`;
// The folders ticked on the Sort page, per home, kept with the layout under these names.
const SHOWN_KEY = { reads: "folders:reads", kept: "folders:kept" } as const;
export type HomeSide = keyof typeof SHOWN_KEY;

const layoutOf = (data: SidebarLayout | undefined): SidebarLayout => data ?? { sections: [], items: {}, hidden: [] };

/** The folders the person took off the sidebar. They keep their mail and rules, and show
 *  under "Show all". */
export function useHiddenFolders() {
  const layout = useSidebar();
  const update = useUpdateSidebar();
  const base = layoutOf(layout.data);
  const hidden = new Set((base.hidden ?? []).filter((id) => id.startsWith("folder:")).map((id) => id.slice("folder:".length)));
  const setHidden = (name: string, hide: boolean) => {
    const rest = (base.hidden ?? []).filter((id) => id !== idOf(name));
    update.mutate({ ...base, hidden: hide ? [...rest, idOf(name)] : rest });
  };
  return { hidden, setHidden };
}

/** The folders each home shows in the sidebar, as ticked on the Sort page. Null until the person
 *  has ticked any, when a home shows its biggest few. */
export function useShownFolders() {
  const layout = useSidebar();
  const update = useUpdateSidebar();
  const base = layoutOf(layout.data);
  const shown = (side: HomeSide): readonly string[] | null => base.items?.[SHOWN_KEY[side]] ?? null;
  const setShown = (chosen: Readonly<Record<HomeSide, readonly string[]>>) =>
    update.mutateAsync({ ...base, items: { ...base.items, [SHOWN_KEY.reads]: [...chosen.reads], [SHOWN_KEY.kept]: [...chosen.kept] } });
  return { shown, setShown };
}
