import { ExternalLink, Mail, WandSparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PriorityBadge } from "@/components/work/priority-badge";
import type { Email } from "@/lib/types";

export function EmailCard({ email }: { email: Email }) {
  return (
    <Card className="p-md">
      <div className="flex items-start justify-between gap-md">
        <div className="flex min-w-0 gap-sm">
          <div className="grid size-2xl shrink-0 place-items-center rounded-lg border border-hairline bg-surface-2">
            <Mail className="size-md text-accent" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-xs">
              <p className="text-small text-ink">{email.sender}</p>
              <span className="text-caption text-ink-tertiary">{email.senderRole}</span>
            </div>
            <h3 className="mt-xs text-heading text-ink">{email.subject}</h3>
            <p className="mt-xs text-small text-ink-subtle">{email.summary}</p>
            <div className="mt-md rounded-md border border-hairline bg-surface-2 p-sm">
              <div className="mb-xxs flex items-center gap-xs text-caption text-accent">
                <WandSparkles className="size-sm" />
                Suggested action
              </div>
              <p className="text-small text-ink-muted">{email.suggestedAction}</p>
            </div>
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-xs">
          <PriorityBadge priority={email.priority} />
          <span className="text-caption text-ink-tertiary">{email.received}</span>
          <Button size="sm" variant="secondary">
            Open
            <ExternalLink className="size-sm" />
          </Button>
        </div>
      </div>
    </Card>
  );
}
