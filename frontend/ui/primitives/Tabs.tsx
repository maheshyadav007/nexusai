"use client";

import * as RadixTabs from "@radix-ui/react-tabs";
import type { ReactNode } from "react";

export interface TabItem {
  value: string;
  label: string;
  content: ReactNode;
}

export function Tabs({ label, tabs, defaultValue }: { label: string; tabs: readonly TabItem[]; defaultValue?: string }) {
  return (
    <RadixTabs.Root defaultValue={defaultValue ?? tabs[0]?.value ?? ""}>
      <RadixTabs.List aria-label={label} className="flex gap-1 border-b border-line-subtle">
        {tabs.map((tab) => (
          <RadixTabs.Trigger key={tab.value} value={tab.value} className="focus-ring -mb-px rounded-t-sm border-b-2 border-transparent px-3 py-2 text-md text-ink-secondary transition-colors duration-fast hover:text-ink-primary data-[state=active]:border-accent-default data-[state=active]:text-ink-primary">
            {tab.label}
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
