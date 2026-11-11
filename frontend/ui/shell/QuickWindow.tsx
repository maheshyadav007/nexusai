"use client";

import { useEffect, type ReactNode } from "react";

/** A page drawn on a see-through window: only the box shows, never a page behind it. */
export function QuickWindow({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.dataset.quick = "true";
    return () => { delete document.documentElement.dataset.quick; };
  }, []);
  return children;
}
