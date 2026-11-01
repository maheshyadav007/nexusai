"use client";

import { BellPlus, Clock3, Sparkles } from "lucide-react";
import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ReminderCard } from "@/components/work/reminder-card";
import { useNexusStore } from "@/lib/store";

export default function RemindersPage() {
  const reminders = useNexusStore((state) => state.reminders);
  const createEntityReminder = useNexusStore((state) => state.createEntityReminder);
  const entityLinked = reminders.filter((reminder) => reminder.entityTitle).length;

  return (
    <>
      <PageHeader
        eyebrow="Reminders"
        title="Memory for things that matter."
        description="Personal reminders, AI-created nudges, and time-sensitive work signals in one queue."
        actions={
          <Button
            variant="primary"
            onClick={() =>
              createEntityReminder({
                title: "Manual reminder: review the priority queue",
                entityTitle: "Priority inbox",
                entityType: "manual",
                trigger: "manual",
                note: "Created from the reminders surface."
              })
            }
          >
            <BellPlus className="size-sm" />
            New reminder
          </Button>
        }
      />
      <div className="mx-auto max-w-page space-y-lg px-xl py-xl">
        <Card className="p-lg">
          <div className="flex flex-wrap items-center justify-between gap-md">
            <div className="flex items-center gap-sm">
            <div className="grid size-2xl place-items-center rounded-lg border border-hairline bg-surface-2">
              <Clock3 className="size-md text-accent" />
            </div>
            <div>
              <h2 className="text-heading text-ink">Next deadline</h2>
              <p className="text-small text-ink-subtle">Supplier risk recommendation is due in 3h 12m.</p>
            </div>
            </div>
            <div className="border border-hairline bg-surface-2 px-sm py-xs text-right">
              <p className="text-heading text-accent">{entityLinked}</p>
              <p className="inline-flex items-center gap-xs text-caption text-ink-subtle">
                <Sparkles className="size-sm" />
                entity-linked
              </p>
            </div>
          </div>
        </Card>
        <div className="grid gap-md lg:grid-cols-2">
          {reminders.map((reminder) => (
            <ReminderCard key={reminder.id} reminder={reminder} />
          ))}
        </div>
      </div>
    </>
  );
}
