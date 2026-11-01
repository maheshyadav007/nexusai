import { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "sticky top-0 z-20 border-b border-hairline bg-canvas/88 px-xl py-lg backdrop-blur-xl",
        className
      )}
    >
      <div className="mx-auto flex max-w-page items-start justify-between gap-lg">
        <div className="min-w-0">
          {eyebrow ? <p className="mb-xs text-caption uppercase text-accent">{eyebrow}</p> : null}
          <h1 className="text-title text-ink">{title}</h1>
          {description ? <p className="mt-xs max-w-reading text-small text-ink-subtle">{description}</p> : null}
        </div>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </div>
    </header>
  );
}
