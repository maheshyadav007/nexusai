"use client";

import * as RadixScrollArea from "@radix-ui/react-scroll-area";
import type { ReactNode } from "react";

export function ScrollArea({ className = "", children }: { className?: string; children: ReactNode }) {
  return (
    <RadixScrollArea.Root type="hover" className={`overflow-hidden ${className}`}>
      <RadixScrollArea.Viewport className="h-full w-full">{children}</RadixScrollArea.Viewport>
      <RadixScrollArea.Scrollbar orientation="vertical" className="flex w-2 p-px">
        <RadixScrollArea.Thumb className="flex-1 rounded-full bg-line-strong" />
      </RadixScrollArea.Scrollbar>
    </RadixScrollArea.Root>
  );
}
