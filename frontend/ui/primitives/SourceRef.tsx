"use client";

import type { KeyboardEvent, MouseEvent } from "react";
import { Icon, type IconName } from "@/ui/icons";
import { Tooltip } from "./Tooltip";

/** How every reference behaves: a click previews it, Cmd/Ctrl-click opens its full page, and
 * Space on a focused one previews it, like Quick Look. The link stays real for the screen reader. */
export function quickLook(onOpen: () => void, onOpenFull?: () => void) {
  return {
    onClick: (event: MouseEvent) => {
      event.preventDefault();
      // A reference inside a row that opens on click opens itself, not the row.
      event.stopPropagation();
      if ((event.metaKey || event.ctrlKey) && onOpenFull) onOpenFull();
      else onOpen();
    },
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key !== " ") return;
      event.preventDefault();
      event.stopPropagation();
      onOpen();
    },
  };
}

/** A small chip naming an email or a document, wherever something came from one. */
const LOOKS = {
  chip: "rounded-full border border-line-subtle px-2 py-px text-ink-secondary hover:bg-surface-sunken",
  // In a row's small grey line: no border, the same grey, darker on hover.
  inline: "rounded-sm text-ink-muted hover:text-ink-primary",
} as const;

export function SourceRef({ icon, title, detail, label, href, onOpen, onOpenFull, look = "chip" }: { icon: IconName; title: string; detail?: string; label?: string; href: string; onOpen: () => void; onOpenFull?: () => void; look?: keyof typeof LOOKS }) {
  return (
    <Tooltip content={[title, detail].filter(Boolean).join(" · ")}>
      <a href={href} data-testid="source-ref" {...quickLook(onOpen, onOpenFull)} className={`focus-ring inline-flex min-w-0 max-w-full items-center gap-1 align-middle text-sm transition-colors duration-fast ${LOOKS[look]}`}>
        <Icon name={icon} className="h-3 w-3 shrink-0 text-ink-muted" />
        <span className="truncate">{label ?? title}</span>
      </a>
    </Tooltip>
  );
}
