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
  /** A line above it, setting it apart from what comes before. */
  divider?: boolean;
  /** A list of its own, opening beside it, such as which matter to merge with. */
  items?: readonly MenuItem[];
  /** On or off. With an icon, a check after the words; without, a box before them, and the
   *  menu stays open so several can be ticked. */
  checked?: boolean;
  /** A small title over the lines that follow, not something to choose. */
  heading?: boolean;
  onSelect?: () => void;
}

export function Menu({ trigger, items, side = "bottom", variant = "default", label }: { trigger: ReactNode; items: readonly MenuItem[]; side?: "top" | "bottom"; variant?: "default" | "account"; label?: string }) {
  const account = variant === "account";
  return (
    <RadixMenu.Root>
      <RadixMenu.Trigger asChild>{trigger}</RadixMenu.Trigger>
      <RadixMenu.Portal>
        <RadixMenu.Content side={side} align="start" sideOffset={account ? 8 : 4} collisionPadding={account ? 8 : 16} aria-label={label} className={`from-trigger z-float border border-line-subtle shadow-overlay ${account ? "account-menu rounded-lg bg-surface-raised p-2" : "animate-pop-in rounded-md data-[state=closed]:animate-pop-out surface-glass p-1"}`}>
          {items.filter((item) => !item.items).map((item) => (
            <RadixMenu.Item key={item.id} {...(item.disabled === undefined ? {} : { disabled: item.disabled })} onSelect={() => item.onSelect?.()} className={`flex cursor-default items-center gap-3 text-md outline-none transition-colors duration-fast data-[disabled]:opacity-60 data-[highlighted]:bg-surface-sunken ${account ? "rounded-md px-3 py-2" : "rounded-sm px-3 py-2"} ${item.danger ? "text-status-danger" : "text-ink-primary"}`}>
              {item.icon ? <Icon name={item.icon} /> : null}
              {item.label}
            </RadixMenu.Item>
          ))}
        </RadixMenu.Content>
      </RadixMenu.Portal>
    </RadixMenu.Root>
  );
}
