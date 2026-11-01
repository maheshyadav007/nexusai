import type { ReactNode } from "react";

/** One setting: what it is on the left, its control on the right, a hairline between rows. */
export function SettingRow({ label, description, children, wide = false }: { label: string; description?: string; children: ReactNode; wide?: boolean }) {
  return (
    <div data-testid="setting-row" className="flex items-center justify-between gap-6 border-b border-line-subtle py-3 first:pt-0 last:border-b-0 last:pb-0">
      <div className="min-w-0 flex-1">
        <p className="text-md text-ink-primary">{label}</p>
        {description ? <p className="mt-px text-sm text-ink-muted">{description}</p> : null}
      </div>
      <div className={`shrink-0 ${wide ? "w-popover max-w-full" : "w-rail-wide"}`}>{children}</div>
    </div>
  );
}
