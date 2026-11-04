import type { ReactNode } from "react";

export function Card({ title, description, aside, children, bare = false }: { title: string; description?: string; aside?: ReactNode; children: ReactNode; bare?: boolean }) {
  return (
    <section className={bare ? "py-1" : "rounded-lg border border-line-subtle bg-surface-raised p-5"}>
      <header className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-medium text-ink-primary">{title}</h2>
          {description ? <p className="mt-1 text-sm text-ink-muted">{description}</p> : null}
        </div>
        {aside}
      </header>
      {children}
    </section>
  );
}
