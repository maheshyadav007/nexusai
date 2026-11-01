"use client";

import { MoreHorizontal, Plus, Settings2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PriorityBadge } from "@/components/work/priority-badge";
import { useNexusStore } from "@/lib/store";
import type { Panel } from "@/lib/types";

export function PanelCard({ panel }: { panel: Panel }) {
  const deletePanel = useNexusStore((state) => state.deletePanel);
  const addNotice = useNexusStore((state) => state.addNotice);

  return (
    <Card className="group p-md">
      <div className="mb-md flex items-start justify-between gap-md">
        <div className="min-w-0">
          <div className="mb-xs flex flex-wrap items-center gap-xs">
            <PriorityBadge priority={panel.priority} />
            <span className="text-caption text-ink-tertiary">{panel.category}</span>
          </div>
          <h3 className="text-heading text-ink">{panel.title}</h3>
        </div>
        <div className="flex shrink-0 items-center gap-xxs opacity-80 transition group-hover:opacity-100">
          <Button
            aria-label="Panel settings"
            size="icon-sm"
            variant="ghost"
            onClick={() =>
              addNotice({
                title: "Panel settings opened",
                description: `${panel.title} settings are mocked in this prototype.`,
                tone: "info"
              })
            }
          >
            <Settings2 className="size-sm" />
          </Button>
          <Button
            aria-label="Delete panel"
            size="icon-sm"
            variant="ghost"
            onClick={() => deletePanel(panel.id)}
          >
            <Trash2 className="size-sm" />
          </Button>
          <Button aria-label="More panel actions" size="icon-sm" variant="ghost">
            <MoreHorizontal className="size-sm" />
          </Button>
        </div>
      </div>
      <div className="space-y-xs">
        {panel.items.map((item) => (
          <div key={item} className="flex items-start gap-xs rounded-md bg-surface-2 p-sm">
            <Plus className="mt-xxs size-sm shrink-0 text-accent" />
            <p className="text-small text-ink-muted">{item}</p>
          </div>
        ))}
      </div>
      <p className="mt-md text-caption text-ink-tertiary">Last updated {panel.lastUpdated}</p>
    </Card>
  );
}
