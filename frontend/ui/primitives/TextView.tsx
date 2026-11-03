"use client";

import { useState, type ReactNode } from "react";
import { t } from "@/ui/strings";
import { Dialog } from "./Dialog";
import { IconButton } from "./IconButton";
import { Textarea } from "./Input";

const WHOLE = "focus-ring min-h-0 flex-1 overflow-auto whitespace-pre-wrap rounded-md bg-surface-sunken p-3 font-mono text-sm text-ink-primary";

/** A button in the corner of any box of text, which opens all of it large. */
function Expand({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog title={title} shape="glass" open={open} onOpenChange={setOpen} trigger={<IconButton icon="openFull" label={t("view.expand", { title })} data-testid="view-expand" />}>
      <div className="mt-3 flex min-h-0 flex-1 flex-col">{children}</div>
    </Dialog>
  );
}

/** Text to read, in a small box with the whole of it a click away. Every prompt and note uses it. */
export function TextView({ title, text, className = "max-h-popover" }: { title: string; text: string; className?: string }) {
  return (
    <div className="relative">
      <pre tabIndex={0} className={`focus-ring overflow-auto whitespace-pre-wrap rounded-md bg-surface-sunken p-2 pr-7 font-mono text-sm text-ink-secondary ${className}`}>{text}</pre>
      <div className="absolute right-1 top-1">
        <Expand title={title}>
          <pre tabIndex={0} className={WHOLE}>{text}</pre>
        </Expand>
      </div>
    </div>
  );
}

/** Text to edit, the same way. */
export function TextEditor({ label, value, onChange, rows = 8 }: { label: string; value: string; onChange: (value: string) => void; rows?: number }) {
  return (
    <div className="relative">
      <Textarea aria-label={label} rows={rows} value={value} onChange={(event) => onChange(event.target.value)} className="pr-7" />
      <div className="absolute right-1 top-1">
        <Expand title={label}>
          <Textarea aria-label={label} value={value} onChange={(event) => onChange(event.target.value)} className="min-h-0 flex-1 font-mono text-sm" />
        </Expand>
      </div>
    </div>
  );
}

export { Expand as ExpandText };
