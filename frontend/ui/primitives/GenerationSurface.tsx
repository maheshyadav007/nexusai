import type { ReactNode } from "react";
import { Icon } from "@/ui/icons";
import { t } from "@/ui/strings";
import { Skeleton } from "./Skeleton";

type GenerationPhase = "preparing" | "idle" | "queued" | "generating" | "done" | "failed" | "stopped";

/** Only an actual model call moves. Preparation, queues and completed results stay still. */
export function GenerationSurface({ phase, label, children, placeholder = false, compact = false, className = "" }: {
  phase: GenerationPhase;
  label: string;
  children?: ReactNode;
  placeholder?: boolean;
  compact?: boolean;
  className?: string;
}) {
  const generating = phase === "generating";
  const queued = phase === "queued";
  const busy = generating || queued || phase === "preparing";
  const status = generating ? label : queued ? t("generation.queued") : t("generation.preparing");
  return (
    <div data-testid="generation-surface" data-phase={phase} aria-busy={busy || undefined}
      className={`generation-surface rounded-md ${generating || queued ? "ai-surface" : "border border-line-subtle bg-surface-sunken"} ${compact ? "px-3 py-2" : "p-4"} ${className}`}>
      {busy ? <div role="status" aria-live="polite" className="flex items-center gap-2 text-md text-ink-secondary">
        <Icon name={generating ? "thinking" : queued ? "schedules" : "loading"} className={`h-4 w-4 shrink-0 ${phase === "preparing" ? "animate-spin motion-reduce:animate-none" : ""}`} />
        <span>{status}</span>
      </div> : null}
      {children}
      {busy && placeholder ? <div aria-hidden className="generation-placeholder mt-4 flex flex-col gap-2"><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-3/4" /><Skeleton className="h-3 w-1/2" /></div> : null}
    </div>
  );
}
