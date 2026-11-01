import type { ReactNode } from "react";

/** A screen's name, one line on what's here, and at most one action. */
export function PageHeader({ title, summary, action }: { title: string; summary?: ReactNode; action?: ReactNode }) {
  return (
    <header className="flex items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="font-serif text-display text-ink-primary">{title}</h1>
        {summary ? <p className="mt-1 text-md tabular-nums text-ink-secondary">{summary}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}
