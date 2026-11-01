"use client";

import * as RadixPopover from "@radix-ui/react-popover";
import type { ReactNode } from "react";

export function Popover({ trigger, label, children }: { trigger: ReactNode; label: string; children: ReactNode }) {
  return (
    <RadixPopover.Root>
      <RadixPopover.Trigger asChild>{trigger}</RadixPopover.Trigger>
      <RadixPopover.Portal>
        <RadixPopover.Content aria-label={label} align="end" sideOffset={8} collisionPadding={16} className="focus-ring z-50 w-popover max-w-full animate-rise rounded-lg border border-line-subtle bg-surface-raised p-4 text-ink-primary shadow-overlay">
          {children}
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}
