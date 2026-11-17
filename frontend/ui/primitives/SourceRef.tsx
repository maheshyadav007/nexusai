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
      if ((event.metaKey || event.ctrlKey) && onOpenFull) onOpenFull();
      else onOpen();
    },
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key !== " ") return;
      event.preventDefault();
      onOpen();
    },
  };
}

/** A small chip naming an email or a document, wherever something came from one. */
export function SourceRef({ icon, title, detail, label, href, onOpen, onOpenFull }: { icon: IconName; title: string; detail?: string; label?: string; href: string; onOpen: () => void; onOpenFull?: () => void }) {
  return (
    <Tooltip content={[title, detail].filter(Boolean).join(" · ")}>
      <a href={href} data-testid="source-ref" {...quickLook(onOpen, onOpenFull)} className="focus-ring inline-flex min-w-0 max-w-full items-center gap-1 rounded-full border border-line-subtle px-2 py-px align-middle text-sm text-ink-secondary transition-colors duration-fast hover:bg-surface-sunken">
        <Icon name={icon} className="h-3 w-3 shrink-0 text-ink-muted" />
        <span className="truncate">{label ?? title}</span>
      </a>
    </Tooltip>
  );
}
