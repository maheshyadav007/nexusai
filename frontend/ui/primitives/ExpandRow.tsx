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
export function ExpandRow({ label, testid, leading, title, meta, aside, children, defaultOpen = false }: { label: string; testid?: string; leading?: ReactNode; title: ReactNode; meta?: ReactNode; aside?: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const feel = useFeel();
  return (
    <motion.div layout="position" initial={false} animate={{ borderRadius: readSpace(open ? light.radius.md : light.radius.lg) }} transition={feel.smooth} data-testid={testid} className={`overflow-hidden border bg-surface-raised transition-colors duration-fast ${open ? "border-line-strong" : "border-line-subtle"}`}>
      <div className="flex items-center gap-3 px-3 py-2">
        {leading}
        {/* The arrow is the control for keyboards and screen readers. The whole row answers a click. */}
        <div onClick={() => setOpen((current) => !current)} className="flex min-w-0 flex-1 cursor-pointer flex-col">
          <span className="min-w-0 truncate text-md text-ink-primary">{title}</span>
          {meta ? <span className="min-w-0 truncate text-sm tabular-nums text-ink-muted">{meta}</span> : null}
        </div>
        {aside}
        <button type="button" aria-expanded={open} aria-label={label} onClick={() => setOpen((current) => !current)} className="focus-ring shrink-0 rounded-sm p-1 text-ink-faint transition-colors duration-fast hover:text-ink-primary">
          <Turn open={open}>
            <Icon name="chevronRight" className="h-3 w-3" />
          </Turn>
        </button>
      </div>
      <Reveal open={open}>
        <div className="flex flex-col gap-3 border-t border-line-subtle p-3">{children}</div>
      </Reveal>
    </motion.div>
  );
}
