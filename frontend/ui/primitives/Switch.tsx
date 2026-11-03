"use client";

import * as RadixSwitch from "@radix-ui/react-switch";
import { useId, useState } from "react";

export function Switch({ label, hideLabel = false, checked, disabled, onChange }: { label: string; hideLabel?: boolean; checked: boolean; disabled?: boolean; onChange: (checked: boolean) => void }) {
  const id = useId();
  // Only once it's been used, or every switch on a page would play its bounce on load.
  const [used, setUsed] = useState(false);
  return (
    <div className="flex items-center justify-between gap-3">
      <label htmlFor={id} className={hideLabel ? "sr-only" : "text-md text-ink-secondary"}>
        {label}
      </label>
      <RadixSwitch.Root
        id={id}
        checked={checked}
        {...(disabled === undefined ? {} : { disabled })}
        onCheckedChange={(next) => {
          setUsed(true);
          onChange(next);
        }}
        className={`t-toggle focus-ring shrink-0 disabled:opacity-60 ${used ? "is-init" : ""}`}
      >
        <RadixSwitch.Thumb className="t-toggle-thumb" />
      </RadixSwitch.Root>
    </div>
  );
}
