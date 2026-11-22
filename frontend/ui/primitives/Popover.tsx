"use client";

import * as RadixPopover from "@radix-ui/react-popover";
import type { ReactNode } from "react";

const SIZES = {
  default: "w-popover p-4",
  // A list to pick from, such as the conversation switcher: wider, with its rows to the edges.
  menu: "w-menu overflow-hidden p-0",
  // Room for a whole panel, such as everything waiting for the person, scrolling inside.
  panel: "w-dialog max-h-modal-height overflow-y-auto p-3",
} as const;

export function Popover({ trigger, label, children, align = "end", size = "default", open, onOpenChange }: { trigger: ReactNode; label: string; children: ReactNode; align?: "start" | "end"; size?: keyof typeof SIZES; open?: boolean; onOpenChange?: (open: boolean) => void }) {
  return (
    <RadixPopover.Root {...(open === undefined ? {} : { open })} {...(onOpenChange ? { onOpenChange } : {})}>
      <RadixPopover.Trigger asChild>{trigger}</RadixPopover.Trigger>
      <RadixPopover.Portal>
        <RadixPopover.Content onOpenAutoFocus={(event) => { event.preventDefault(); (event.currentTarget as HTMLElement).focus(); }} aria-label={label} align={align} sideOffset={8} collisionPadding={16} className={`focus-ring z-float max-w-full from-trigger animate-pop-in rounded-lg data-[state=closed]:animate-pop-out border border-line-subtle bg-surface-raised text-ink-primary shadow-overlay ${SIZES[size]}`}>
          {children}
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}
