"use client";

import * as RadioGroup from "@radix-ui/react-radio-group";
import { motion } from "motion/react";
import { useId, type ReactNode } from "react";
import { QUICK } from "./motion";

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
          {value === tile.value ? <motion.span layoutId={ring} transition={QUICK} className="absolute inset-0 rounded-md border-2 border-accent-default" /> : null}
          <span className="relative">{tile.preview}</span>
          <span className="relative px-1 pb-1 text-sm text-ink-secondary transition-colors duration-fast group-data-[state=checked]:text-ink-primary">{tile.label}</span>
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  );
}
