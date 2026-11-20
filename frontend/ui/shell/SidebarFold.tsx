"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import appConfig from "@/app.config.json";
import { Icon, type IconName } from "@/ui/icons";
import { Pressable } from "@/ui/primitives/Pressable";

type Folds = Record<string, boolean>;

function readFolds(): Folds {
  try {
    return JSON.parse(localStorage.getItem(appConfig.storageKeys.sidebarFolds) ?? "{}") as Folds;
  } catch {
    // Storage can be blocked or hold something else; every fold then starts closed.
    return {};
  }
}

/** A sidebar section that stays folded until opened, and remembers. It opens by itself while the
 *  page shown is inside it, so the open folder is never hidden. */
export function SidebarFold({ id, icon, label, count, holdsActive, children }: { id: string; icon: IconName; label: string; count?: number; holdsActive: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  useEffect(() => setOpen(Boolean(readFolds()[id])), [id]);
  const shown = open || holdsActive;
  const toggle = () => {
    const next = !shown;
    setOpen(next);
    try {
      localStorage.setItem(appConfig.storageKeys.sidebarFolds, JSON.stringify({ ...readFolds(), [id]: next }));
    } catch {
      // Storage can be blocked; the choice then lasts until reload.
    }
  };
  return (
    <section aria-label={label} className="flex shrink-0 flex-col">
      <Pressable aria-expanded={shown} aria-controls={panel} onClick={toggle} className="flex items-center gap-2 rounded-md px-2 py-px text-md text-ink-secondary transition-colors duration-fast hover:bg-surface-raised hover:text-ink-primary">
        <Icon name={icon} />
        <span className="min-w-0 flex-1 truncate text-left">{label}</span>
        {count ? <span className="text-sm tabular-nums text-ink-muted">{count.toLocaleString()}</span> : null}
        <Icon name="chevronDown" className={`h-4 w-4 text-ink-muted transition-transform duration-fast ${shown ? "" : "-rotate-90"}`} />
      </Pressable>
      {/* Closed, its rows aren't there at all, so nothing hidden can be reached by keyboard. */}
      <div id={panel} hidden={!shown} className="pl-3">
        {shown ? children : null}
      </div>
    </section>
  );
}
