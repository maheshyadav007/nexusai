"use client";

import { useSidebar, useUpdateSidebar } from "@/ui/client/settings";
import type { SidebarLayout } from "@/ui/client/contracts.generated";

// A folder left out of the sidebar is kept with the rest of its layout, under this name.
const idOf = (name: string) => `folder:${name}`;

/** The folders the person took off the sidebar. They keep their mail and rules, and show
 *  under "Show all". */
export function useHiddenFolders() {
  const layout = useSidebar();
  const update = useUpdateSidebar();
  const base: SidebarLayout = layout.data ?? { sections: [], items: {}, hidden: [] };
  const hidden = new Set((base.hidden ?? []).filter((id) => id.startsWith("folder:")).map((id) => id.slice("folder:".length)));
  const setHidden = (name: string, hide: boolean) => {
    const rest = (base.hidden ?? []).filter((id) => id !== idOf(name));
    update.mutate({ ...base, hidden: hide ? [...rest, idOf(name)] : rest });
  };
  return { hidden, setHidden };
}
