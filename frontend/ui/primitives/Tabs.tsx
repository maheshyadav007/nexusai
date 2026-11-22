"use client";

import * as RadixTabs from "@radix-ui/react-tabs";
import { useId, useState, type ReactNode } from "react";
import { ActiveMark } from "./Motion";

export interface TabItem {
  value: string;
  label: string;
  content: ReactNode;
}

/** Keeps its own place, or follows `value` and reports changes, when the page owns it (a URL). */
export function Tabs({ label, tabs, defaultValue, value, onValueChange }: { label: string; tabs: readonly TabItem[]; defaultValue?: string; value?: string; onValueChange?: (value: string) => void }) {
  const [own, setOwn] = useState(defaultValue ?? tabs[0]?.value ?? "");
  const current = value ?? own;
  const setCurrent = (next: string) => {
    setOwn(next);
    onValueChange?.(next);
  };
  const group = useId();
  return (
    <RadixTabs.Root value={current} onValueChange={setCurrent}>
      <RadixTabs.List aria-label={label} className="flex flex-wrap gap-1 border-b border-line-subtle">
        {tabs.map((tab) => (
          <RadixTabs.Trigger key={tab.value} value={tab.value} className="focus-ring relative rounded-t-sm px-3 py-2 text-md text-ink-secondary transition-colors duration-fast hover:text-ink-primary data-[state=active]:text-ink-primary">
            {tab.label}
            {current === tab.value ? <ActiveMark group={group} className="absolute inset-x-0 bottom-0 h-px bg-accent-default" /> : null}
          </RadixTabs.Trigger>
        ))}
      </RadixTabs.List>
      {tabs.map((tab) => (
        <RadixTabs.Content key={tab.value} value={tab.value} className="focus-ring pt-4 text-md text-ink-secondary">
          {tab.content}
        </RadixTabs.Content>
      ))}
    </RadixTabs.Root>
  );
}
