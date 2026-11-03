"use client";

import * as RadixCheckbox from "@radix-ui/react-checkbox";
import { useId } from "react";
import { Icon } from "@/ui/icons";
import { Tick } from "./Motion";

export function Checkbox({ label, hideLabel = false, checked, disabled, onChange }: { label: string; hideLabel?: boolean; checked: boolean; disabled?: boolean; onChange: (checked: boolean) => void }) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <RadixCheckbox.Root id={id} checked={checked} {...(disabled === undefined ? {} : { disabled })} onCheckedChange={(next) => onChange(next === true)} className="focus-ring flex h-4 w-4 items-center justify-center rounded-sm border border-line-strong bg-surface-raised text-accent-on transition-colors duration-fast disabled:opacity-60 data-[state=checked]:border-accent-default data-[state=checked]:bg-accent-default">
        <RadixCheckbox.Indicator>
          <Tick>
            <Icon name="check" className="h-3 w-3" />
          </Tick>
        </RadixCheckbox.Indicator>
      </RadixCheckbox.Root>
      <label htmlFor={id} className={hideLabel ? "sr-only" : "text-md text-ink-primary"}>
        {label}
      </label>
    </div>
  );
}

/** The round tick beside a to-do. Its label is for screen readers, since the row already shows it. */
export function RoundCheck({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <RadixCheckbox.Root aria-label={label} checked={checked} onCheckedChange={(next) => onChange(next === true)} className={`focus-ring press flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${checked ? "border-status-success bg-status-success text-surface-raised" : "border-line-strong hover:border-ink-muted"}`}>
      <RadixCheckbox.Indicator asChild>
        <Tick>
          <Icon name="check" className="h-3 w-3" />
        </Tick>
      </RadixCheckbox.Indicator>
    </RadixCheckbox.Root>
  );
}
