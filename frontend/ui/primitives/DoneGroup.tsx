"use client";

import { useState, type ReactNode } from "react";
import { Icon } from "@/ui/icons";
import { Reveal, Turn } from "./Motion";

/**
 * What's finished, the same everywhere: one line with the count at the bottom of a list, closed
 * until it's asked for. Matters, tasks, reminders and the brief all use it.
 */
export function DoneGroup({ label, count, children, testid, defaultOpen = false }: { label: string; count: number; children: ReactNode; testid?: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  if (!count) return null;
  return (
    <div data-testid={testid} className="flex flex-col border-t border-line-subtle pt-2">
      <button type="button" aria-expanded={open} onClick={() => setOpen((current) => !current)} className="focus-ring flex items-center gap-2 self-start py-2 rounded-sm text-sm font-medium text-ink-muted transition-colors duration-fast hover:text-ink-primary">
        <Turn open={open}>
          <Icon name="chevronRight" className="h-3 w-3" />
        </Turn>
        {label}
        <span className="tabular-nums">{count}</span>
      </button>
      <Reveal open={open}>
        <ul className="flex flex-col">{children}</ul>
      </Reveal>
    </div>
  );
}

/** One finished thing: a check, its title struck through and faint, and when or how it was done. */
export function DoneRow({ title, meta, action, testid, onOpen, current = false }: { title: ReactNode; meta?: ReactNode; action?: ReactNode; testid?: string; onOpen?: () => void; current?: boolean }) {
  const words = (
    <>
      <span className="min-w-0 break-words text-md line-through">{title}</span>
      {meta ? <span className="text-sm tabular-nums">{meta}</span> : null}
    </>
  );
  return (
    <li data-testid={testid} className={`flex items-start gap-2 rounded-md py-2 text-ink-faint ${onOpen ? "px-2" : ""} ${current ? "bg-surface-sunken" : ""}`}>
      <Icon name="check" className="mt-px h-4 w-4 shrink-0 text-status-success" />
      {/* Something done can still be opened, to read it back. */}
      {onOpen ? (
        <button type="button" aria-current={current ? "true" : undefined} onClick={onOpen} className="focus-ring flex min-w-0 flex-1 flex-col rounded-sm text-left transition-colors duration-fast hover:text-ink-secondary">{words}</button>
      ) : (
        <span className="flex min-w-0 flex-1 flex-col">{words}</span>
      )}
      {action}
    </li>
  );
}
