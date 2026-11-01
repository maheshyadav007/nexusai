import { CalendarPlus, TriangleAlert } from "lucide-react";
import { PageHeader } from "@/components/app/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CalendarCard } from "@/components/work/calendar-card";
import { calendarEvents } from "@/lib/data";

export default function CalendarPage() {
  return (
    <>
      <PageHeader
        eyebrow="Calendar"
        title="Meetings with context attached."
        description="NexusAI connects your schedule to emails, tasks, draft replies, and enterprise issues."
        actions={
          <Button variant="primary">
            <CalendarPlus className="size-sm" />
            Schedule
          </Button>
        }
      />
      <div className="mx-auto max-w-page space-y-lg px-xl py-xl">
        <Card className="border-status-warning/30 bg-status-warning/10 p-lg">
          <div className="flex items-start gap-sm">
            <TriangleAlert className="mt-xxs size-md text-status-warning" />
            <div>
              <div className="flex flex-wrap items-center gap-xs">
                <h2 className="text-heading text-ink">Calendar conflict detected</h2>
                <Badge variant="high">Needs action</Badge>
              </div>
              <p className="mt-xs text-small text-ink-subtle">
                Supplier risk review overlaps with renewal preparation. NexusAI suggests moving renewal prep to 15:00.
              </p>
            </div>
          </div>
        </Card>
        <div className="grid gap-md lg:grid-cols-2">
          {calendarEvents.map((event) => (
            <CalendarCard key={event.id} event={event} />
          ))}
        </div>
      </div>
    </>
  );
}
