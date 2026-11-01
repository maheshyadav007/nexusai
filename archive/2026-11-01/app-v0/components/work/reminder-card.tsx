import { Bell, Check, Clock3, Link2, RotateCcw, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { Reminder } from "@/lib/types";

export function ReminderCard({ reminder }: { reminder: Reminder }) {
  const tone = reminder.status === "due" ? "high" : reminder.status === "complete" ? "success" : "default";

  return (
    <Card className="p-md">
      <div className="flex items-start justify-between gap-md">
        <div className="flex gap-sm">
          <div className="grid size-2xl shrink-0 place-items-center rounded-lg border border-hairline bg-surface-2">
            <Bell className="size-md text-accent" />
          </div>
          <div>
            <div className="mb-xs flex flex-wrap items-center gap-xs">
              <Badge variant={tone}>{reminder.status}</Badge>
              <span className="text-caption text-ink-tertiary">{reminder.owner}</span>
              {reminder.trigger ? (
                <Badge variant="default">
                  <Sparkles className="size-sm" />
                  {reminder.trigger}
                </Badge>
              ) : null}
            </div>
            <h3 className="text-heading text-ink">{reminder.title}</h3>
            {reminder.entityTitle ? (
              <p className="mt-xs inline-flex items-center gap-xs text-caption text-ink-subtle">
                <Link2 className="size-sm text-accent" />
                {reminder.entityType}: {reminder.entityTitle}
              </p>
            ) : null}
            <div className="mt-sm flex flex-wrap items-center gap-sm text-small text-ink-subtle">
              <span className="inline-flex items-center gap-xs">
                <Clock3 className="size-sm" />
                {reminder.dueTime}
              </span>
              <span className="text-accent">{reminder.countdown}</span>
            </div>
            {reminder.note ? <p className="mt-xs text-caption text-ink-tertiary">{reminder.note}</p> : null}
          </div>
        </div>
      </div>
      <div className="mt-md flex gap-xs">
        <Button size="sm" variant="secondary">
          <RotateCcw className="size-sm" />
          Snooze
        </Button>
        <Button size="sm" variant="primary">
          <Check className="size-sm" />
          Complete
        </Button>
      </div>
    </Card>
  );
}
