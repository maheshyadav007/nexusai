"use client";

import { useSidebar, useUpdateSidebar } from "@/ui/client/settings";
import type { SidebarLayout } from "@/ui/client/contracts.generated";

// A folder left out of the sidebar is kept with the rest of its layout, under this name.
const idOf = (name: string) => `folder:${name}`;
// Set once the person has ticked folders on the Sort page.
const CHOSEN = "folders:chosen";

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

/** Whether the person chose on the Sort page which folders the sidebar shows. Before that a home
 *  shows its biggest few; after, every folder except those unticked there or hidden here, so a
 *  folder made or renamed later shows too. */
export function useShownFolders() {
  const layout = useSidebar();
  const update = useUpdateSidebar();
  const base = layoutOf(layout.data);
  const chosen = Boolean(base.items?.[CHOSEN]?.length);
  const setShown = (shown: readonly string[], unticked: readonly string[]) => {
    const touched = new Set([...shown, ...unticked].map(idOf));
    return update.mutateAsync({ ...base, hidden: [...(base.hidden ?? []).filter((id) => !touched.has(id)), ...unticked.map(idOf)], items: { ...base.items, [CHOSEN]: ["sort"] } });
  };
  return { chosen, setShown };
}
