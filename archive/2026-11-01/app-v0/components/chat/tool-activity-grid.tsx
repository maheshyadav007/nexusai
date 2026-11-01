import { CheckCircle2, CircleDashed, Loader2, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { ToolRun, WorkStatus } from "@/lib/types";

const statusIcon: Record<WorkStatus, typeof CircleDashed> = {
  pending: CircleDashed,
  running: Loader2,
  success: CheckCircle2,
  failed: TriangleAlert
};

export function ToolActivityGrid({ tools }: { tools: ToolRun[] }) {
  return (
    <div className="mb-md grid gap-sm lg:grid-cols-2">
      {tools.map((tool) => {
        const Icon = statusIcon[tool.status];
        return (
          <div key={tool.id} className="rounded-lg border border-hairline bg-surface-1 p-md">
            <div className="mb-sm flex items-start justify-between gap-md">
              <div className="min-w-0">
                <p className="truncate text-small text-ink">{tool.name}</p>
                <p className="text-caption text-ink-tertiary">{tool.duration}</p>
              </div>
              <Badge
                variant={
                  tool.status === "success"
                    ? "success"
                    : tool.status === "running"
                      ? "running"
                      : tool.status === "failed"
                        ? "failed"
                        : "default"
                }
              >
                <Icon className={tool.status === "running" ? "size-sm animate-spin" : "size-sm"} />
                {tool.status}
              </Badge>
            </div>
            <div className="space-y-xs">
              <div className="rounded-md bg-surface-2 p-sm">
                <p className="mb-xxs text-caption text-ink-tertiary">Input</p>
                <p className="text-small text-ink-muted">{tool.input}</p>
              </div>
              <div className="rounded-md bg-surface-2 p-sm">
                <p className="mb-xxs text-caption text-ink-tertiary">Output</p>
                <p className="text-small text-ink-muted">
                  {tool.status === "pending" ? "Waiting for execution..." : tool.output}
                </p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
