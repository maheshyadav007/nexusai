"use client";

import * as RadixMenu from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";
import { Icon, type IconName } from "@/ui/icons";

export interface MenuItem {
  id: string;
  label: string;
  icon?: IconName;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

export function Menu({ trigger, items }: { trigger: ReactNode; items: readonly MenuItem[] }) {
  return (
    <RadixMenu.Root>
      <RadixMenu.Trigger asChild>{trigger}</RadixMenu.Trigger>
      <RadixMenu.Portal>
        <RadixMenu.Content align="start" sideOffset={4} collisionPadding={16} className="from-trigger z-50 animate-pop-in rounded-md data-[state=closed]:animate-pop-out border border-line-subtle bg-surface-raised p-1 shadow-overlay">
          {items.map((item) => (
            <RadixMenu.Item key={item.id} {...(item.disabled === undefined ? {} : { disabled: item.disabled })} onSelect={item.onSelect} className={`flex cursor-default items-center gap-2 rounded-sm px-2 py-1 text-md outline-none data-[disabled]:opacity-60 data-[highlighted]:bg-surface-sunken ${item.danger ? "text-status-danger" : "text-ink-primary"}`}>
              {item.icon ? <Icon name={item.icon} /> : null}
              {item.label}
            </RadixMenu.Item>
          ))}
        </RadixMenu.Content>
      </RadixMenu.Portal>
    </RadixMenu.Root>
  );
}
