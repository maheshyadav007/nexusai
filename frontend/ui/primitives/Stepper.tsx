import { Icon } from "@/ui/icons";

/** `skipped` are behind the current step but weren't done, so they don't get marked as done. */
export function Stepper({ label, steps, current, skipped }: { label: string; steps: readonly string[]; current: number; skipped?: ReadonlySet<number> }) {
  return (
    <ol aria-label={label} className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {steps.map((step, index) => (
        <li key={step} aria-current={index === current ? "step" : undefined} className={`flex items-center gap-2 text-sm tabular-nums ${index === current ? "font-medium text-ink-primary" : "text-ink-muted"}`}>
          <span aria-hidden className={`h-2 w-2 rounded-full ${index < current && !skipped?.has(index) ? "bg-agent-done" : index === current ? "bg-accent-default" : "bg-line-strong"}`} />
          {step}
        </li>
      ))}
    </ol>
  );
}

/** The same steps down the side of a page, with room to see where you are in them. */
export function StepRail({ label, steps, current, skipped, skippedLabel }: { label: string; steps: readonly string[]; current: number; skipped?: ReadonlySet<number>; skippedLabel?: string }) {
  return (
    <ol aria-label={label} className="flex flex-col gap-1">
      {steps.map((step, index) => {
        const passed = index < current;
        const done = passed && !skipped?.has(index);
        return (
          <li key={step} data-testid={passed ? (done ? "step-done" : "step-skipped") : undefined} aria-current={index === current ? "step" : undefined} className={`flex items-center gap-3 rounded-md px-2 py-1 text-md transition-colors duration-normal ${index === current ? "bg-surface-sunken font-medium text-ink-primary" : passed ? "text-ink-secondary" : "text-ink-muted"}`}>
            <span aria-hidden className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-colors duration-normal ${done ? "border-agent-done bg-agent-done text-surface-raised" : index === current ? "border-accent-default" : "border-line-strong text-ink-muted"}`}>
              {done ? <Icon name="check" className="h-3 w-3" /> : passed ? <Icon name="skipped" className="h-3 w-3" /> : null}
            </span>
            <span className="flex min-w-0 flex-1 items-baseline justify-between gap-2">
              {step}
              {passed && !done && skippedLabel ? <span className="text-sm text-ink-muted">{skippedLabel}</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
