"use client";

import { useDateTime } from "@/ui/client/format";
import { SourceRef } from "@/ui/primitives/SourceRef";
import { useOpenSource } from "./context";
import { fullHref, SOURCE_ICONS, type PreviewSource } from "./kinds";

/** Where something came from, as one chip that opens the quick preview. Used everywhere a source shows. */
export function SourceChip({ source, list, label, look = "chip" }: { source: PreviewSource; list?: readonly PreviewSource[]; label?: string; look?: "chip" | "inline" }) {
  const preview = useOpenSource();
  const format = useDateTime();
  const detail = [source.detail, source.date ? format(source.date) : ""].filter(Boolean).join(" · ");
  return (
    <SourceRef
      icon={SOURCE_ICONS[source.kind]}
      title={source.title ?? label ?? ""}
      {...(detail ? { detail } : {})}
      {...(label ? { label } : {})}
      href={fullHref(source)}
      onOpen={() => preview.open(source, list)}
      onOpenFull={() => preview.openFull(source)}
      look={look}
    />
  );
}
