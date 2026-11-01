"use client";

import * as RadixCheckbox from "@radix-ui/react-checkbox";
import { useId } from "react";
import { Icon } from "@/ui/icons";

export function Checkbox({ label, checked, disabled, onChange }: { label: string; checked: boolean; disabled?: boolean; onChange: (checked: boolean) => void }) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <RadixCheckbox.Root id={id} checked={checked} {...(disabled === undefined ? {} : { disabled })} onCheckedChange={(next) => onChange(next === true)} className="focus-ring flex h-4 w-4 items-center justify-center rounded-sm border border-line-strong bg-surface-raised text-accent-on transition-colors duration-fast disabled:opacity-60 data-[state=checked]:border-accent-default data-[state=checked]:bg-accent-default">
        <RadixCheckbox.Indicator>
          <Icon name="check" className="h-3 w-3" />
        </RadixCheckbox.Indicator>
      </RadixCheckbox.Root>
      <label htmlFor={id} className="text-md text-ink-primary">
        {label}
      </label>
    </div>
  );
}
