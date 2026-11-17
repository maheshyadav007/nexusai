"use client";

import { motion } from "motion/react";
import { useState, type ReactNode } from "react";
import { Icon } from "@/ui/icons";
import light from "@/ui/theme/themes/nexus-light.json";
import { readSpace, Reveal, Turn, useFeel } from "./Motion";

/**
 * One item that opens in place to show more. Its corners tighten when open, as Beautiful UI's task
 * rows do, so the shape itself says what state it's in.
 */
export function ExpandRow({ label, testid, leading, title, meta, aside, children, defaultOpen = false, variant = "card" }: { label: string; testid?: string; leading?: ReactNode; title: ReactNode; meta?: ReactNode; aside?: ReactNode; children: ReactNode; defaultOpen?: boolean; variant?: "card" | "plain" | "list" }) {
  const [open, setOpen] = useState(defaultOpen);
  const feel = useFeel();
  // "list" is a row on a ListGroup panel: no rule lines, the same look as ListRow.
  const list = variant === "list";
  const radius = variant === "plain" ? 0 : readSpace(list ? light.radius.md : open ? light.radius.md : light.radius.lg);
  const frame = variant === "plain" ? "border-b border-line-subtle" : list ? (open ? "bg-surface-sunken/40" : "") : `border bg-surface-raised ${open ? "border-line-strong" : "border-line-subtle"}`;
  return (
    <motion.div layout="position" initial={false} animate={{ borderRadius: radius }} transition={feel.smooth} data-testid={testid} className={`overflow-hidden transition-colors duration-fast ${frame}`}>
      <div className={`group flex items-center gap-3 py-3 ${variant === "plain" ? "px-1 hover:bg-surface-sunken/40" : list ? "rounded-md px-3 hover:bg-surface-sunken" : "px-3"}`}>
        {leading}
        {/* The arrow is the control for keyboards and screen readers. The whole row answers a click. */}
        <div onClick={() => setOpen((current) => !current)} className="flex min-w-0 flex-1 cursor-pointer flex-col">
          <span className="min-w-0 break-words text-md text-ink-primary">{title}</span>
          {meta ? <span className={`min-w-0 truncate text-sm tabular-nums ${list ? "mt-1 text-ink-faint" : "text-ink-muted"}`}>{meta}</span> : null}
        </div>
        {aside}
        <button type="button" aria-expanded={open} aria-label={label} onClick={() => setOpen((current) => !current)} className="focus-ring shrink-0 rounded-sm p-1 text-ink-faint transition-colors duration-fast hover:text-ink-primary">
          <Turn open={open}>
            <Icon name="chevronRight" className="h-3 w-3" />
          </Turn>
        </button>
      </div>
      <Reveal open={open}>
        <div className={`flex flex-col gap-3 p-3 ${variant === "plain" ? "mb-3 ml-5 border-t border-line-subtle bg-surface-sunken/30" : list ? "mx-3 mb-2" : "border-t border-line-subtle"}`}>{children}</div>
      </Reveal>
    </motion.div>
  );
}
