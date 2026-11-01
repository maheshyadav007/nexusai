"use client";

import * as RadixSwitch from "@radix-ui/react-switch";
import { useId } from "react";

export function Switch({ label, hideLabel = false, checked, disabled, onChange }: { label: string; hideLabel?: boolean; checked: boolean; disabled?: boolean; onChange: (checked: boolean) => void }) {
  const id = useId();
  return (
    <div className="flex items-center justify-between gap-3">
      <label htmlFor={id} className={hideLabel ? "sr-only" : "text-md text-ink-secondary"}>
        {label}
      </label>
      <RadixSwitch.Root id={id} checked={checked} {...(disabled === undefined ? {} : { disabled })} onCheckedChange={onChange} className="focus-ring inline-flex w-6 rounded-full bg-line-strong p-px transition-colors duration-fast disabled:opacity-60 data-[state=checked]:bg-accent-default">
        <RadixSwitch.Thumb className="block h-3 w-3 rounded-full bg-surface-raised transition-transform duration-fast data-[state=checked]:translate-x-3" />
      </RadixSwitch.Root>
    </div>
  );
}
