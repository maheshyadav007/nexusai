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
