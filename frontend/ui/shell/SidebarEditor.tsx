"use client";

import { useState } from "react";
import { useResetSidebar, useSidebar, useUpdateSidebar } from "@/ui/client/settings";
import type { SidebarLayout } from "@/ui/client/contracts.generated";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { IconButton } from "@/ui/primitives/IconButton";
import { ScrollArea } from "@/ui/primitives/ScrollArea";
import { Sortable } from "@/ui/primitives/Sortable";
import { Switch } from "@/ui/primitives/Switch";
import { t } from "@/ui/strings";
import { NAV_SECTIONS } from "./nav";
import { arrange } from "./sidebarLayout";

export function SidebarEditor() {
  const [open, setOpen] = useState(false);
  const layout = useSidebar();
  const update = useUpdateSidebar();
  const reset = useResetSidebar();
  const sections = arrange(NAV_SECTIONS, layout.data);
  const base: SidebarLayout = layout.data ?? { sections: [], items: {}, hidden: [] };
  const hidden = base.hidden ?? [];
  const setHidden = (id: string, hide: boolean) => update.mutate({ ...base, hidden: hide ? [...hidden, id] : hidden.filter((entry) => entry !== id) });
  return (
    <Dialog title={t("sidebar.editor.title")} description={t("sidebar.editor.description")} shape="drawer" open={open} onOpenChange={setOpen} trigger={<IconButton icon="customize" label={t("sidebar.editor.title")} />}>
      <ScrollArea className="h-drawer">
        <Sortable
          label={t("sidebar.editor.sections")}
          items={sections.map((section) => ({
            id: section.id,
            label: t(section.label),
            content: (
              <div className="flex flex-col gap-2 py-2">
                <Switch label={t(section.label)} checked={!section.hidden} onChange={(show) => setHidden(section.id, !show)} />
                {section.hidden ? null : (
                  <Sortable
                    label={t(section.label)}
                    items={section.items.map((item) => ({
                      id: item.id,
                      label: t(item.label),
                      content: <Switch label={t(item.label)} checked={!item.hidden} onChange={(show) => setHidden(item.id, !show)} />,
                    }))}
                    onReorder={(ids) => update.mutate({ ...base, items: { ...base.items, [section.id]: ids } })}
                  />
                )}
              </div>
            ),
          }))}
          onReorder={(ids) => update.mutate({ ...base, sections: ids })}
        />
      </ScrollArea>
      <div className="mt-4">
        <Button loading={reset.isPending} onClick={() => reset.mutate(undefined)}>
          {t("sidebar.editor.reset")}
        </Button>
      </div>
    </Dialog>
  );
}
