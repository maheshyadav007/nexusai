"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import appConfig from "@/app.config.json";
import { Icon } from "@/ui/icons";
import { Pressable } from "@/ui/primitives/Pressable";

type Folds = Record<string, boolean>;

function readFolds(): Folds {
  try {
    return JSON.parse(localStorage.getItem(appConfig.storageKeys.sidebarFolds) ?? "{}") as Folds;
  } catch {
    // Storage can be blocked or hold something else; every fold then starts as it's made.
    return {};
  }
}

/** A group in the sidebar: a quiet heading like Agent's or Planner's, with its rows under it at
 *  the same level as the rows above. It folds by its heading and remembers, and opens by itself
 *  while the page shown is inside it, so the open folder is never hidden. */
export function SidebarFold({ id, label, actions, open: startOpen = false, remember = true, holdsActive, children }: { id: string; label: string; actions?: ReactNode; open?: boolean; remember?: boolean; holdsActive: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(startOpen);
  const panel = useId();
  useEffect(() => {
    const saved = remember ? readFolds()[id] : undefined;
    if (saved !== undefined) setOpen(saved);
  }, [id, remember]);
  // One that isn't remembered folds again when the page shown leaves it.
  useEffect(() => {
    if (!remember && !holdsActive) setOpen(false);
  }, [remember, holdsActive]);
  const shown = open || holdsActive;
  const toggle = () => {
    const next = !shown;
    setOpen(next);
    if (!remember) return;
    try {
      localStorage.setItem(appConfig.storageKeys.sidebarFolds, JSON.stringify({ ...readFolds(), [id]: next }));
    } catch {
      // Storage can be blocked; the choice then lasts until reload.
    }
  };
  return (
    // Not a landmark of its own: the list inside is named, and the heading's button says what it folds.
    <div className="flex shrink-0 flex-col gap-1">
      <div className="flex items-center gap-1 pr-1">
        <Pressable aria-expanded={shown} aria-controls={panel} onClick={toggle} className="group flex min-w-0 flex-1 items-center gap-1 rounded-sm px-2 py-px text-left text-sm text-ink-muted transition-colors duration-fast hover:text-ink-primary">
          <span className="min-w-0 truncate">{label}</span>
          <Icon name="chevronDown" className={`h-3 w-3 shrink-0 opacity-0 transition duration-fast group-hover:opacity-100 group-focus-visible:opacity-100 ${shown ? "" : "-rotate-90 opacity-100"}`} />
        </Pressable>
        {actions}
      </div>
      {/* Closed, its rows aren't there at all, so nothing hidden can be reached by keyboard. */}
      <div id={panel} hidden={!shown}>
        {shown ? children : null}
      </div>
    </div>
  );
}
