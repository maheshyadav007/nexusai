"use client";

import * as RadioGroup from "@radix-ui/react-radio-group";
import { motion } from "motion/react";
import { useId } from "react";
import { QUICK } from "./motion";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

export function Segmented<T extends string>({ label, hideLabel = false, value, options, onChange }: { label: string; hideLabel?: boolean; value: T | undefined; options: readonly SegmentedOption<T>[]; onChange: (value: T) => void }) {
  const thumb = useId();
  return (
    <div className={`flex flex-wrap items-center gap-3 ${hideLabel ? "justify-end" : "justify-between"}`}>
      {hideLabel ? null : <span className="text-md text-ink-secondary">{label}</span>}
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
            className="focus-ring relative rounded-sm px-3 py-1 text-sm text-ink-secondary transition-colors duration-fast hover:text-ink-primary data-[state=checked]:text-ink-primary"
          >
            {value === option.value ? <motion.span layoutId={thumb} transition={QUICK} className="absolute inset-0 rounded-sm bg-surface-raised shadow-raised" /> : null}
            <span className="relative">{option.label}</span>
          </RadioGroup.Item>
        ))}
      </RadioGroup.Root>
    </div>
  );
}
