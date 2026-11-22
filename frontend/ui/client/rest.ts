"use client";

import { useSyncExternalStore } from "react";

// When one thing in a matter is finished, the rest of the matter is asked about once. Any screen
// that finishes something says so here; one sheet, mounted once, does the asking.
let asked: string | null = null;
const listeners = new Set<() => void>();

/** Something just finished, as "task:88" or "thread:12". */
export function askAboutRest(ref: string): void {
  asked = ref;
  for (const listener of listeners) listener();
}

export function useRestQuestion(): [string | null, () => void] {
  const current = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => asked,
    () => null,
  );
  return [current, () => askAboutRest("")];
}
