"use client";

import * as RadixSelect from "@radix-ui/react-select";
import { Icon } from "@/ui/icons";
import { controlClass } from "./Input";

export interface SelectOption {
  value: string;
  label: string;
}

export function Select({ id, value, options, placeholder, invalid = false, disabled, describedBy, onChange }: { id?: string; value?: string; options: readonly SelectOption[]; placeholder?: string; invalid?: boolean; disabled?: boolean; describedBy?: string; onChange: (value: string) => void }) {
  return (
    <RadixSelect.Root {...(value === undefined ? {} : { value })} onValueChange={onChange} {...(disabled === undefined ? {} : { disabled })}>
      <RadixSelect.Trigger id={id} aria-describedby={describedBy} aria-invalid={invalid || undefined} className={`${controlClass(invalid)} flex items-center justify-between gap-2 text-left`}>
        <RadixSelect.Value {...(placeholder ? { placeholder } : {})} />
        <RadixSelect.Icon>
          <Icon name="chevronDown" />
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
