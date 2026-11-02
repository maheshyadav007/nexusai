"use client";

import * as RadixContextMenu from "@radix-ui/react-context-menu";
import type { ReactNode } from "react";
import { Icon } from "@/ui/icons";
import type { MenuItem } from "./Menu";

/** The same items as a Menu, on right-click or the keyboard's menu key. One list feeds both. */
export function ContextMenu({ items, children }: { items: readonly MenuItem[]; children: ReactNode }) {
  if (!items.length) return <>{children}</>;
  return (
    <RadixContextMenu.Root modal={false}>
      <RadixContextMenu.Trigger asChild>{children}</RadixContextMenu.Trigger>
      <RadixContextMenu.Portal>
        <RadixContextMenu.Content collisionPadding={16} className="surface-glass from-trigger z-50 animate-pop-in rounded-md border border-line-subtle p-1 shadow-overlay data-[state=closed]:animate-pop-out">
          {items.map((item) => (
            <RadixContextMenu.Item key={item.id} {...(item.disabled === undefined ? {} : { disabled: item.disabled })} onSelect={item.onSelect} className={`flex cursor-default items-center gap-2 rounded-sm px-2 py-1 text-md outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-surface-sunken ${item.danger ? "text-status-danger" : "text-ink-primary"}`}>
              {item.icon ? <Icon name={item.icon} /> : null}
              {item.label}
            </RadixContextMenu.Item>
          ))}
        </RadixContextMenu.Content>
      </RadixContextMenu.Portal>
    </RadixContextMenu.Root>
  );
}
