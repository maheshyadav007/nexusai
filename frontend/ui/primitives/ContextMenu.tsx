"use client";

import * as RadixContextMenu from "@radix-ui/react-context-menu";
import { Fragment, type ReactNode } from "react";
import { Icon } from "@/ui/icons";
import type { MenuItem } from "./Menu";

const ITEM = "flex cursor-default items-center gap-2 rounded-sm px-2 py-1 text-md outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-surface-sunken data-[state=open]:bg-surface-sunken";
const PANEL = "surface-glass from-trigger z-float animate-pop-in rounded-md border border-line-subtle p-1 shadow-overlay data-[state=closed]:animate-pop-out";

function Items({ items }: { items: readonly MenuItem[] }) {
  return (
    <>
      {items.map((item) => (
        <Fragment key={item.id}>
          {item.divider ? <RadixContextMenu.Separator className="my-1 h-px bg-line-subtle" /> : null}
          {item.items ? (
            <RadixContextMenu.Sub>
              <RadixContextMenu.SubTrigger {...(item.disabled === undefined ? {} : { disabled: item.disabled || !item.items.length })} className={`${ITEM} text-ink-primary`}>
                {item.icon ? <Icon name={item.icon} /> : null}
                <span className="flex-1">{item.label}</span>
                <Icon name="chevronRight" className="h-3 w-3 text-ink-muted" />
              </RadixContextMenu.SubTrigger>
              <RadixContextMenu.Portal>
                <RadixContextMenu.SubContent collisionPadding={16} className={PANEL}>
                  <Items items={item.items} />
                </RadixContextMenu.SubContent>
              </RadixContextMenu.Portal>
            </RadixContextMenu.Sub>
          ) : (
            <RadixContextMenu.Item {...(item.disabled === undefined ? {} : { disabled: item.disabled })} onSelect={() => item.onSelect?.()} className={`${ITEM} ${item.danger ? "text-status-danger" : "text-ink-primary"}`}>
              {item.icon ? <Icon name={item.icon} /> : null}
              {item.label}
            </RadixContextMenu.Item>
          )}
        </Fragment>
      ))}
    </>
  );
}

/** The same items as a Menu, on right-click, the keyboard's menu key or a long press. One list
 *  feeds both. An item can open a list of its own beside it. */
export function ContextMenu({ items, children }: { items: readonly MenuItem[]; children: ReactNode }) {
  if (!items.length) return <>{children}</>;
  return (
    <RadixContextMenu.Root modal={false}>
      <RadixContextMenu.Trigger asChild>{children}</RadixContextMenu.Trigger>
      <RadixContextMenu.Portal>
        <RadixContextMenu.Content collisionPadding={16} className={PANEL}>
          <Items items={items} />
        </RadixContextMenu.Content>
      </RadixContextMenu.Portal>
    </RadixContextMenu.Root>
  );
}
