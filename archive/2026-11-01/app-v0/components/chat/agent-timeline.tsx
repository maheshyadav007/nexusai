import { Check, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function AgentTimeline({
  steps,
  currentStep
}: {
  steps: string[];
  currentStep: number;
}) {
  return (
    <div className="mb-md rounded-lg border border-hairline bg-surface-1 p-md">
      <div className="mb-sm flex items-center justify-between gap-md">
        <p className="text-small text-ink">Agent execution timeline</p>
        <span className="text-caption text-ink-tertiary">{currentStep + 1}/{steps.length}</span>
      </div>
      <div className="grid gap-xs">
        {steps.map((step, index) => {
          const isDone = index < currentStep;
          const isRunning = index === currentStep;

          return (
            <div key={step} className="flex items-center gap-sm">
              <div
                className={cn(
                  "grid size-lg place-items-center rounded-full border text-caption",
                  isDone && "border-status-success bg-status-success/15 text-ink",
                  isRunning && "border-accent bg-accent/15 text-ink",
                  !isDone && !isRunning && "border-hairline bg-surface-2 text-ink-tertiary"
                )}
              >
                {isDone ? (
                  <Check className="size-sm" />
                ) : isRunning ? (
                  <Loader2 className="size-sm animate-spin" />
                ) : (
                  index + 1
                )}
              </div>
              <div className="h-px flex-1 bg-hairline" />
              <span
                className={cn(
                  "w-[var(--timeline-label-width)] text-small",
                  isDone && "text-ink-muted",
                  isRunning && "text-ink",
                  !isDone && !isRunning && "text-ink-tertiary"
                )}
              >
                {step}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
