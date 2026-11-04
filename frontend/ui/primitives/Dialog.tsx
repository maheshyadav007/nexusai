"use client";

import * as RadixDialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { t } from "@/ui/strings";
import { IconButton } from "./IconButton";

const SHAPES = {
  dialog: { overlay: "grid grid-cols-1 place-items-center p-5", panel: "w-dialog max-w-full animate-dialog-in rounded-lg data-[state=closed]:animate-dialog-out" },
  drawer: { overlay: "flex justify-end", panel: "h-full w-drawer max-w-full animate-drawer-in border-l data-[state=closed]:animate-drawer-out" },
  // Frosted and roomy, for what needs space: settings, and reading a document.
  palette: { overlay: "glass-backdrop bg-surface-scrim/40 flex justify-center p-5 pt-10", panel: "surface-glass flex max-h-full w-dialog max-w-full animate-dialog-in flex-col self-start rounded-lg border data-[state=closed]:animate-dialog-out" },
  // The backdrop does the blurring: browsers only blur what's inside the nearest layer.
  glass: { overlay: "glass-backdrop bg-surface-scrim/40 grid grid-cols-1 place-items-center p-5", panel: "surface-glass flex h-modal-height max-h-full w-modal max-w-full animate-dialog-in flex-col rounded-lg border data-[state=closed]:animate-dialog-out" },
} as const;

/** A centered dialog, or a drawer from the right edge. Focus, Escape and scroll lock come from Radix. */
export function Dialog({ title, description, trigger, shape = "dialog", open, onOpenChange, children }: { title: string; description?: string; trigger?: ReactNode; shape?: keyof typeof SHAPES; open?: boolean; onOpenChange?: (open: boolean) => void; children: ReactNode }) {
  return (
    <RadixDialog.Root {...(open === undefined ? {} : { open })} {...(onOpenChange ? { onOpenChange } : {})}>
      {trigger ? <RadixDialog.Trigger asChild>{trigger}</RadixDialog.Trigger> : null}
      <RadixDialog.Portal>
        <RadixDialog.Overlay className={`fixed inset-0 z-40 animate-fade data-[state=closed]:animate-fade-out ${shape === "glass" || shape === "palette" ? "" : "bg-surface-scrim/40"} ${SHAPES[shape].overlay}`}>
          <RadixDialog.Content {...(description ? {} : { "aria-describedby": undefined })} className={`border-line-subtle p-5 text-ink-primary shadow-overlay ${shape === "glass" || shape === "palette" ? "" : "bg-surface-raised"} ${SHAPES[shape].panel}`}>
            <header className="mb-4 flex items-start justify-between gap-4">
              <div>
                <RadixDialog.Title className="text-lg font-medium">{title}</RadixDialog.Title>
                {description ? <RadixDialog.Description className="mt-1 text-md text-ink-muted">{description}</RadixDialog.Description> : null}
              </div>
              <RadixDialog.Close asChild>
                <IconButton icon="close" label={t("common.close")} tooltip={false} />
              </RadixDialog.Close>
            </header>
            {children}
          </RadixDialog.Content>
        </RadixDialog.Overlay>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
