import type { ReactNode } from "react";

/** A soft wave either side of a short note, for a moment worth marking in a conversation. */
function Wave() {
  return (
    <svg aria-hidden className="h-2 min-w-0 flex-1 text-line-strong" preserveAspectRatio="none" viewBox="0 0 120 8">
      <path d="M0 4 Q 7.5 0 15 4 T 30 4 T 45 4 T 60 4 T 75 4 T 90 4 T 105 4 T 120 4" fill="none" stroke="currentColor" strokeWidth="1" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function WavyDivider({ children }: { children: ReactNode }) {
  return (
    <div role="separator" className="flex items-center gap-3 py-2 text-sm tabular-nums text-ink-muted">
      <Wave />
      <span className="shrink-0">{children}</span>
      <Wave />
    </div>
  );
}
