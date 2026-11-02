"use client";

import { useDateTime } from "@/ui/client/format";
import { usePreview } from "@/ui/features/documents/DocumentPreview";
import { SourcesPill, type SourceRow } from "@/ui/primitives/Citation";
import { t, tn } from "@/ui/strings";
import type { MessageSource } from "./parts";

/** Opens a cited email or document over the page, without leaving the conversation. */
export function useOpenSource() {
  const preview = usePreview();
  return (source: MessageSource) => {
    if (source.kind === "mail") preview.showThread(Number(source.ref));
    else preview.show({ key: source.ref });
  };
}

export function MessageSources({ sources }: { sources: readonly MessageSource[] }) {
  const open = useOpenSource();
  const format = useDateTime();
  if (!sources.length) return null;
  const rows: SourceRow[] = sources.map((source) => ({
    id: `${source.kind}-${source.ref}`,
    icon: source.kind === "mail" ? "inbox" : "documents",
    title: source.title,
    detail: [source.detail, source.page, source.date ? format(source.date) : ""].filter(Boolean).join(" · "),
    number: source.n,
    onOpen: () => open(source),
  }));
  return <SourcesPill label={tn("chat.sources", sources.length)} sources={rows} heading={{ cited: t("chat.sources.cited"), read: t("chat.sources.read") }} />;
}
