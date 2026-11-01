"use client";

import {
  Activity,
  Bot,
  CalendarClock,
  Mail,
  RadioTower,
  Sparkles,
  Timer
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  actionItems,
  automations,
  calendarEvents,
  importantEmails,
  reminders
} from "@/lib/data";
import { cn } from "@/lib/utils";

function RailSection({
  title,
  icon: Icon,
  children
}: {
  title: string;
  icon: typeof Activity;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-hairline bg-surface-1/72 p-md">
      <div className="mb-sm flex items-center gap-xs text-caption text-ink-subtle">
        <Icon className="size-sm text-accent" />
        <span>{title}</span>
      </div>
      {children}
    </section>
  );
}

export function RightIntelligencePanel() {
  return (
    <aside className="intelligence-panel h-screen overflow-y-auto border-l border-hairline bg-canvas px-md py-md">
      <div className="mb-lg flex items-center justify-between">
        <div>
          <p className="text-small text-ink">Intelligence</p>
          <p className="text-caption text-ink-subtle">Updated just now</p>
        </div>
        <Badge variant="running">
          <span className="status-dot" />
          Online
        </Badge>
      </div>

      <div className="space-y-sm">
        <RailSection title="Upcoming reminders" icon={Timer}>
          <div className="space-y-xs">
            {reminders.slice(0, 2).map((reminder) => (
              <div key={reminder.id} className="rounded-md bg-surface-2 p-sm">
                <div className="flex items-start justify-between gap-sm">
                  <p className="text-small text-ink">{reminder.title}</p>
                  <span className="text-caption text-accent">{reminder.countdown}</span>
                </div>
                <p className="mt-xxs text-caption text-ink-subtle">{reminder.dueTime}</p>
              </div>
            ))}
          </div>
        </RailSection>

        <RailSection title="Today's calendar" icon={CalendarClock}>
          <div className="space-y-xs">
            {calendarEvents.slice(0, 2).map((event) => (
              <div key={event.id} className="rounded-md bg-surface-2 p-sm">
                <div className="flex items-center justify-between gap-sm">
                  <p className="truncate text-small text-ink">{event.title}</p>
                  <Badge variant={event.status === "conflict" ? "critical" : "default"}>
                    {event.status}
                  </Badge>
                </div>
                <p className="mt-xxs text-caption text-ink-subtle">{event.time}</p>
              </div>
            ))}
          </div>
        </RailSection>

        <RailSection title="Important emails" icon={Mail}>
          <div className="space-y-xs">
            {importantEmails.slice(0, 2).map((email) => (
              <div key={email.id} className="rounded-md bg-surface-2 p-sm">
                <p className="text-small text-ink">{email.sender}</p>
                <p className="mt-xxs line-clamp-2 text-caption text-ink-subtle">{email.subject}</p>
              </div>
            ))}
          </div>
        </RailSection>

        <RailSection title="Action items" icon={Bot}>
          <div className="space-y-xs">
            {actionItems.slice(0, 3).map((item) => (
              <div key={item.id} className="flex items-start gap-xs rounded-md bg-surface-2 p-sm">
                <span
                  className={cn(
                    "mt-xs size-xs rounded-full",
                    item.priority === "critical" && "bg-status-danger",
                    item.priority === "high" && "bg-status-warning",
                    item.priority === "medium" && "bg-status-info"
                  )}
                />
                <div className="min-w-0">
                  <p className="line-clamp-2 text-small text-ink">{item.task}</p>
                  <p className="text-caption text-ink-subtle">{item.due}</p>
                </div>
              </div>
            ))}
          </div>
        </RailSection>

        <RailSection title="System status" icon={RadioTower}>
          <div className="grid gap-xs">
            {["Email sync", "Calendar graph", "Enterprise index"].map((status) => (
              <div key={status} className="flex items-center justify-between rounded-md bg-surface-2 p-sm">
                <span className="text-small text-ink-muted">{status}</span>
                <Badge variant="success">Healthy</Badge>
              </div>
            ))}
          </div>
        </RailSection>

        <RailSection title="Suggested automations" icon={Sparkles}>
          <div className="space-y-xs">
            {automations.slice(0, 2).map((automation) => (
              <div key={automation.id} className="rounded-md bg-surface-2 p-sm">
                <p className="text-small text-ink">{automation.title}</p>
                <p className="mt-xxs text-caption text-ink-subtle">{automation.impact}</p>
              </div>
            ))}
          </div>
          <Button className="mt-sm w-full" size="sm" variant="secondary">
            Review automations
          </Button>
        </RailSection>
      </div>
    </aside>
  );
}
