"use client";

import * as RadioGroup from "@radix-ui/react-radio-group";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

export function Segmented<T extends string>({ label, value, options, onChange }: { label: string; value: T | undefined; options: readonly SegmentedOption<T>[]; onChange: (value: T) => void }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <span className="text-md text-ink-secondary">{label}</span>
      <RadioGroup.Root
        aria-label={label}
        value={value ?? ""}
        onValueChange={(next) => onChange(next as T)}
        className="inline-flex gap-1 rounded-md bg-surface-sunken p-1"
      >
        {options.map((option) => (
          <RadioGroup.Item
            key={option.value}
            value={option.value}
            className="rounded-sm px-3 py-1 text-sm text-ink-secondary transition-colors duration-fast hover:text-ink-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-default data-[state=checked]:bg-surface-raised data-[state=checked]:text-ink-primary data-[state=checked]:shadow-raised"
          >
            {option.label}
          </RadioGroup.Item>
        ))}
      </RadioGroup.Root>
    </div>
  );
}
