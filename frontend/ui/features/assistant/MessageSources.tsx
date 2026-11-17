"use client";

import { useDateTime } from "@/ui/client/format";
import { useOpenSource } from "@/ui/features/sources/context";
import { SOURCE_ICONS } from "@/ui/features/sources/kinds";
import { SourcesPill, type SourceRow } from "@/ui/primitives/Citation";
import { t, tn } from "@/ui/strings";
import type { MessageSource } from "./parts";

export function MessageSources({ sources }: { sources: readonly MessageSource[] }) {
  const preview = useOpenSource();
  const format = useDateTime();
  if (!sources.length) return null;
  const rows: SourceRow[] = sources.map((source) => ({
    id: `${source.kind}-${source.ref}`,
    icon: SOURCE_ICONS[source.kind],
    title: source.title,
    detail: [source.detail, source.page, source.date ? format(source.date) : ""].filter(Boolean).join(" · "),
    number: source.n,
    onOpen: () => preview.open(source, sources),
  }));
  return <SourcesPill label={tn("chat.sources", sources.length)} sources={rows} heading={{ cited: t("chat.sources.cited"), read: t("chat.sources.read") }} />;
}
