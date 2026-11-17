"use client";

import { useRouter } from "next/navigation";
import { createContext, use, useMemo, type ReactNode } from "react";
import { fullHref, type PreviewSource } from "./kinds";

export interface SourcePreview {
  /** Opens it over the page. Others from the same list can then be reached with the arrow keys. */
  open: (source: PreviewSource, list?: readonly PreviewSource[]) => void;
}

// Outside the app itself, such as during setup, there's nothing to open these over.
export const SourcePreviewContext = createContext<SourcePreview>({ open: () => undefined });

/** Opens a source in the quick preview, or with openFull on its own page. */
export function useOpenSource() {
  const preview = use(SourcePreviewContext);
  const router = useRouter();
  return useMemo(() => ({ open: preview.open, openFull: (source: PreviewSource) => router.push(fullHref(source)) }), [preview.open, router]);
}

/** Where there's no room to read, such as the quick-ask box: sources open in the app instead. */
export function PreviewInApp({ open, children }: { open: (link: string) => void; children: ReactNode }) {
  const value = useMemo(() => ({ open: (source: PreviewSource) => open(fullHref(source)) }), [open]);
  return <SourcePreviewContext value={value}>{children}</SourcePreviewContext>;
}
