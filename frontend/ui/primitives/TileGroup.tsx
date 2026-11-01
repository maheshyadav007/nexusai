"use client";

import * as RadioGroup from "@radix-ui/react-radio-group";
import { useId, type ReactNode } from "react";
import { ActiveMark } from "./Motion";

export interface Tile<T extends string> {
  value: T;
  label: string;
  /** A small preview of what choosing this looks like. */
  preview: ReactNode;
}

/** Choices that are easier to see than to read, like themes. */
export function TileGroup<T extends string>({ label, value, tiles, onChange }: { label: string; value: T | undefined; tiles: readonly Tile<T>[]; onChange: (value: T) => void }) {
  const ring = useId();
  return (
    <RadioGroup.Root aria-label={label} value={value ?? ""} onValueChange={(next) => onChange(next as T)} className="flex flex-wrap gap-3">
      {tiles.map((tile) => (
        <RadioGroup.Item key={tile.value} value={tile.value} className="focus-ring group relative flex flex-col items-start gap-2 rounded-md p-1 text-left">
          {value === tile.value ? <ActiveMark group={ring} className="absolute inset-0 rounded-md border-2 border-accent-default" /> : null}
          <span className="relative">{tile.preview}</span>
          <span className="relative px-1 pb-1 text-sm text-ink-secondary transition-colors duration-fast group-data-[state=checked]:text-ink-primary">{tile.label}</span>
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  );
}

/** Choices that need a sentence each, such as how much the agent may do. */
export function ChoiceCards<T extends string>({ label, value, choices, onChange }: { label: string; value: T | undefined; choices: readonly { value: T; label: string; description: string }[]; onChange: (value: T) => void }) {
  const ring = useId();
  return (
    <RadioGroup.Root aria-label={label} value={value ?? ""} onValueChange={(next) => onChange(next as T)} className="flex flex-col gap-2">
      {choices.map((choice) => (
        <RadioGroup.Item key={choice.value} value={choice.value} className="focus-ring press relative flex flex-col gap-1 rounded-md border border-line-subtle bg-surface-raised p-3 text-left hover:bg-surface-sunken">
          {value === choice.value ? <ActiveMark group={ring} className="absolute inset-0 rounded-md border-2 border-accent-default" /> : null}
          <span className="relative text-md font-medium text-ink-primary">{choice.label}</span>
          <span className="relative text-sm text-ink-muted">{choice.description}</span>
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  );
}
