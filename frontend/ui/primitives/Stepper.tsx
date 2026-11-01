import { Icon } from "@/ui/icons";

export function Stepper({ label, steps, current }: { label: string; steps: readonly string[]; current: number }) {
  return (
    <ol aria-label={label} className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {steps.map((step, index) => (
        <li key={step} aria-current={index === current ? "step" : undefined} className={`flex items-center gap-2 text-sm tabular-nums ${index === current ? "font-medium text-ink-primary" : "text-ink-muted"}`}>
          <span aria-hidden className={`h-2 w-2 rounded-full ${index < current ? "bg-agent-done" : index === current ? "bg-accent-default" : "bg-line-strong"}`} />
          {step}
        </li>
      ))}
    </ol>
  );
}

/** The same steps down the side of a page, with room to see where you are in them. */
export function StepRail({ label, steps, current }: { label: string; steps: readonly string[]; current: number }) {
  return (
    <ol aria-label={label} className="flex flex-col gap-1">
      {steps.map((step, index) => (
        <li key={step} aria-current={index === current ? "step" : undefined} className={`flex items-center gap-3 rounded-md px-2 py-1 text-md transition-colors duration-normal ${index === current ? "bg-surface-sunken font-medium text-ink-primary" : index < current ? "text-ink-secondary" : "text-ink-muted"}`}>
          <span aria-hidden className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-colors duration-normal ${index < current ? "border-agent-done bg-agent-done text-surface-raised" : index === current ? "border-accent-default" : "border-line-strong"}`}>
            {index < current ? <Icon name="check" className="h-3 w-3" /> : null}
          </span>
          {step}
        </li>
      ))}
    </ol>
  );
}
