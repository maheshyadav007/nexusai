"use client";

import { useCallback, useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";
import { DocumentPreviewPanel } from "@/ui/features/documents/DocumentPreview";
import { SourcePreviewContext } from "./context";
import { sameSource, type PreviewSource } from "./kinds";
import { MailPreview } from "./MailPreview";
import type { PreviewProps } from "./PreviewFrame";

// How each kind of source shows in the quick preview. A new kind is one more line here, and its
// full page one more case in kinds.fullHref.
const PREVIEWS: Record<PreviewSource["kind"], ComponentType<PreviewProps>> = {
  mail: MailPreview,
  doc: DocumentPreviewPanel,
  file: DocumentPreviewPanel,
};

/** Any email or document opens here, over the page and the chat, from wherever it was clicked. */
export function SourcePreviewProvider({ children }: { children: ReactNode }) {
  const [list, setList] = useState<readonly PreviewSource[]>([]);
  const [position, setPosition] = useState(-1);
  const source = list[position];
  const open = useCallback((chosen: PreviewSource, siblings?: readonly PreviewSource[]) => {
    const all = siblings?.length ? siblings : [chosen];
    const found = all.findIndex((item) => sameSource(item, chosen));
    // The one clicked keeps its own message or page, even if the list's copy has none.
    setList(found < 0 ? [chosen] : all.map((item, index) => (index === found ? chosen : item)));
    setPosition(Math.max(found, 0));
  }, []);
  const move = useCallback((by: number) => setPosition((current) => Math.min(Math.max(current + by, 0), list.length - 1)), [list.length]);
  const close = useCallback(() => setPosition(-1), []);
  const showing = Boolean(source);
  useEffect(() => {
    if (!showing) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      const typing = target instanceof HTMLElement && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable);
      if (typing) return;
      if (event.key === "ArrowLeft") move(-1);
      if (event.key === "ArrowRight") move(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showing, move]);
  const value = useMemo(() => ({ open }), [open]);
  const Preview = source ? PREVIEWS[source.kind] : null;
  return (
    <SourcePreviewContext value={value}>
      {children}
      {source && Preview ? <Preview source={source} position={position} total={list.length} onMove={move} onClose={close} /> : null}
    </SourcePreviewContext>
  );
}
