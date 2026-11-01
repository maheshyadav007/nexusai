"use client";

import * as RadixSelect from "@radix-ui/react-select";
import { Icon } from "@/ui/icons";
import { controlClass } from "./Input";

export interface SelectOption {
  value: string;
  label: string;
}

export function Select({ id, label, value, options, placeholder, invalid = false, disabled, describedBy, onChange, quiet = false, compact = false }: { quiet?: boolean; compact?: boolean; id?: string; label?: string; value?: string; options: readonly SelectOption[]; placeholder?: string; invalid?: boolean; disabled?: boolean; describedBy?: string; onChange: (value: string) => void }) {
  return (
    <RadixSelect.Root {...(value === undefined ? {} : { value })} onValueChange={onChange} {...(disabled === undefined ? {} : { disabled })}>
      <RadixSelect.Trigger id={id} aria-label={label} aria-describedby={describedBy} aria-invalid={invalid || undefined} className={quiet ? "focus-ring inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm text-ink-secondary transition-colors duration-fast hover:bg-surface-sunken hover:text-ink-primary" : `${controlClass(invalid)} flex items-center justify-between gap-2 text-left ${compact ? "py-1" : ""}`}>
        <RadixSelect.Value {...(placeholder ? { placeholder } : {})} />
        <RadixSelect.Icon>
          <Icon name="chevronDown" className={quiet ? "h-3 w-3 shrink-0" : "h-4 w-4 shrink-0"} />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>
      <RadixSelect.Portal>
        <RadixSelect.Content position="popper" sideOffset={4} className="z-50 w-popover max-w-full animate-rise rounded-md border border-line-subtle bg-surface-raised p-1 text-ink-primary shadow-overlay">
          <RadixSelect.Viewport>
            {options.map((option) => (
              <RadixSelect.Item key={option.value} value={option.value} className="flex cursor-default items-center justify-between gap-2 rounded-sm px-2 py-1 text-md outline-none data-[highlighted]:bg-surface-sunken">
                <RadixSelect.ItemText>{option.label}</RadixSelect.ItemText>
                <RadixSelect.ItemIndicator>
                  <Icon name="check" />
                </RadixSelect.ItemIndicator>
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}
