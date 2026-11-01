import { ExternalLink, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { SourceCard } from "@/lib/types";

export function SourceGrid({ sources }: { sources: SourceCard[] }) {
  return (
    <Card className="p-lg">
      <div className="mb-md flex items-center justify-between gap-md">
        <div>
          <h3 className="text-heading text-ink">Sources</h3>
          <p className="mt-xxs text-small text-ink-subtle">Workspace citations used for this answer.</p>
        </div>
        <span className="text-caption text-ink-tertiary">{sources.length} sources</span>
      </div>
      <div className="grid gap-sm md:grid-cols-2">
        {sources.map((source, index) => (
          <div key={source.id} className="rounded-lg border border-hairline bg-surface-2 p-md">
            <div className="mb-sm flex items-start justify-between gap-sm">
              <div className="flex min-w-0 items-start gap-sm">
                <div className="grid size-2xl shrink-0 place-items-center rounded-md border border-hairline bg-surface-1 text-small text-accent">
                  {index + 1}
                </div>
                <div className="min-w-0">
                  <p className="truncate text-small text-ink">{source.title}</p>
                  <p className="text-caption text-ink-tertiary">{source.origin}</p>
                </div>
              </div>
              <FileText className="size-md shrink-0 text-ink-tertiary" />
            </div>
            <p className="mb-sm text-small text-ink-subtle">{source.snippet}</p>
            <div className="flex items-center justify-between gap-sm">
              <span className="text-caption text-accent">{source.confidence} confidence</span>
              <Button size="sm" variant="ghost">
                Open
                <ExternalLink className="size-sm" />
              </Button>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
