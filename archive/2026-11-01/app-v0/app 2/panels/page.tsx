"use client";

import { Plus, SlidersHorizontal } from "lucide-react";
import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { PanelCard } from "@/components/work/panel-card";
import { useNexusStore } from "@/lib/store";

export default function PanelsPage() {
  const panels = useNexusStore((state) => state.panels);
  const addPanel = useNexusStore((state) => state.addPanel);

  return (
    <>
      <PageHeader
        eyebrow="Panels"
        title="AI-generated work surfaces."
        description="Each panel is a compact, refreshable lens over email, meetings, PLM, issues, reminders, drafts, and follow-ups."
        actions={
          <div className="flex gap-xs">
            <Button variant="secondary">
              <SlidersHorizontal className="size-sm" />
              Configure
            </Button>
            <Button variant="primary" onClick={addPanel}>
              <Plus className="size-sm" />
              Add panel
            </Button>
          </div>
        }
      />
      <div className="mx-auto grid max-w-page gap-md px-xl py-xl lg:grid-cols-2 xl:grid-cols-3">
        {panels.map((panel) => (
          <PanelCard key={panel.id} panel={panel} />
        ))}
      </div>
    </>
  );
}
