"use client";

import type { ReactNode } from "react";
import { Pressable } from "./Pressable";

/** A titled group of rows on one soft panel. Sessions, tasks and reminders all use it, so a list
 * reads the same everywhere: the heading above, rows spaced on the panel, no rule lines between. */
export function ListGroup({ title, detail, tone = "default", label, children }: { title: string; detail?: string | undefined; tone?: "default" | "waiting" | "danger"; label?: string; children: ReactNode }) {
  const color = tone === "waiting" ? "text-agent-waiting" : tone === "danger" ? "text-status-danger" : "text-ink-primary";
  return (
    <section aria-label={label ?? title} className="flex flex-col gap-2">
      <h2 className={`mx-1 flex items-baseline gap-2 text-md font-medium ${color}`}>
        {title}
        {detail ? <span className="font-normal text-ink-muted">{detail}</span> : null}
      </h2>
      <ul className="flex flex-col rounded-lg border border-line-subtle bg-surface-raised p-1">{children}</ul>
    </section>
  );
}

const LEAD = {
  // A dot, a tick box or a small tile.
  icon: "w-6",
  // A time such as 10:30 PM.
  time: "w-guide",
} as const;

/** One row: what leads it (a tick box, a time, an avatar), its title, one small grey line about
 * it, and what can be done with it. Pass onOpen and the body becomes the button that opens it. */
export function ListRow({ lead, leadWidth = "icon", title, meta, trailing, onOpen, testid, state }: { lead?: ReactNode; leadWidth?: keyof typeof LEAD; title: ReactNode; meta?: ReactNode; trailing?: ReactNode; onOpen?: () => void; testid?: string; state?: string }) {
  const body = (
    <span className="flex min-w-0 flex-1 flex-col gap-1">
      <span className="min-w-0 truncate text-md text-ink-primary">{title}</span>
      {meta ? <span className="flex min-w-0 items-center gap-2 text-sm text-ink-muted">{meta}</span> : null}
    </span>
  );
  return (
    <li data-testid={testid} data-state={state} className="group flex items-center gap-3 rounded-md px-3 transition-colors duration-fast hover:bg-surface-sunken">
      {lead !== undefined ? <span className={`flex shrink-0 items-center justify-center ${LEAD[leadWidth]}`}>{lead}</span> : null}
      {onOpen ? (
        <Pressable onClick={onOpen} className="focus-ring flex min-w-0 flex-1 rounded-md py-3 text-left">{body}</Pressable>
      ) : (
        <div className="flex min-w-0 flex-1 py-3">{body}</div>
      )}
      {trailing ? <span className="flex shrink-0 items-center gap-1">{trailing}</span> : null}
    </li>
  );
}

/** A small dot between bits of a meta line. */
export function MetaDot() {
  return <span aria-hidden className="h-1 w-1 shrink-0 rounded-full bg-line-strong" />;
}
