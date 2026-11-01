import { CalendarDays, MapPin, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { CalendarEvent } from "@/lib/types";

export function CalendarCard({ event }: { event: CalendarEvent }) {
  const tone = event.status === "conflict" ? "critical" : event.status === "tentative" ? "medium" : "success";

  return (
    <Card className="p-md">
      <div className="flex items-start gap-sm">
        <div className="grid size-2xl shrink-0 place-items-center rounded-lg border border-hairline bg-surface-2">
          <CalendarDays className="size-md text-accent" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-xs">
            <h3 className="text-heading text-ink">{event.title}</h3>
            <Badge variant={tone}>{event.status}</Badge>
          </div>
          <p className="mt-xs text-small text-accent">{event.time}</p>
          <div className="mt-md grid gap-xs text-small text-ink-subtle">
            <span className="inline-flex items-center gap-xs">
              <Users className="size-sm" />
              {event.attendees.join(", ")}
            </span>
            <span className="inline-flex items-center gap-xs">
              <MapPin className="size-sm" />
              {event.location}
            </span>
          </div>
        </div>
      </div>
      <Button className="mt-md w-full" size="sm" variant="secondary">
        Open meeting
      </Button>
    </Card>
  );
}
