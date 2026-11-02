"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { Icon } from "@/ui/icons";
import { useCategories, useSaveCategory } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { Dialog } from "@/ui/primitives/Dialog";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { ActiveMark } from "@/ui/primitives/Motion";
import { t } from "@/ui/strings";

const EDIT_CATEGORIES = "/settings?section=categories";

function NewCategory() {
  const save = useSaveCategory();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [sender, setSender] = useState("");
  const [priority, setPriority] = useState(false);
  const failed = save.error instanceof ApiRequestError ? save.error.detail.message : null;
  return (
    <Dialog title={t("categories.new")} description={t("categories.new.description")} open={open} onOpenChange={setOpen} trigger={<IconButton icon="add" label={t("categories.new")} />}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate(
            { name: name.trim(), in_priority: priority, ...(sender.trim() ? { sender: sender.trim() } : {}) },
            {
              onSuccess: () => {
                setOpen(false);
                setName("");
                setSender("");
                setPriority(false);
              },
            },
          );
        }}
      >
        <Field label={t("categories.name")} {...(failed ? { error: failed } : {})}>{({ invalid, ...control }) => <Input invalid={invalid} value={name} onChange={(event) => setName(event.target.value)} {...control} />}</Field>
        <Field label={t("categories.sender")} hint={t("categories.sender.hint")}>{({ invalid, ...control }) => <Input invalid={invalid} spellCheck={false} value={sender} onChange={(event) => setSender(event.target.value)} {...control} />}</Field>
        <Checkbox label={t("categories.priority")} checked={priority} onChange={setPriority} />
        <div className="flex justify-end">
          <Button type="submit" variant="primary" loading={save.isPending} disabled={!name.trim()}>
            {t("categories.create")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/** Folders the person or an agent made. They live in the sidebar beside the fixed ones. */
export function CategoryNav({ collapsed }: { collapsed: boolean }) {
  const categories = useCategories();
  const pathname = usePathname();
  const router = useRouter();
  if (collapsed) return null;
  const rows = (categories.data?.categories ?? []).filter((item) => !item.proposed);
  return (
    <section aria-label={t("nav.categories")}>
      <ul className="flex flex-col gap-px">
        {rows.map((item) => {
          const href = `/mail/category/${encodeURIComponent(item.name)}`;
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <li key={item.name} data-testid="nav-category">
              <ContextMenu items={[{ id: "open", label: t("menu.open"), onSelect: () => router.push(href) }, { id: "edit", label: t("menu.editCategory"), onSelect: () => router.push(EDIT_CATEGORIES) }]}>
              <Link href={href} aria-current={active ? "page" : undefined} className={`focus-ring press relative flex items-center gap-2 rounded-md px-2 py-1 text-md transition-colors duration-fast ${active ? "text-ink-primary" : "text-ink-secondary hover:bg-surface-raised hover:text-ink-primary"}`}>
                {active ? <ActiveMark group="nav-active" /> : null}
                <span aria-hidden className={`relative flex shrink-0 ${item.in_priority ? "text-accent-default" : ""}`}>
                  <Icon name="folder" />
                </span>
                <span className="relative min-w-0 flex-1 truncate">{item.name}</span>
                {item.unread ? <span className="relative text-sm tabular-nums text-ink-muted">{item.unread}</span> : null}
              </Link>
              </ContextMenu>
            </li>
          );
        })}
        <li className="flex justify-end pr-1">
          <NewCategory />
        </li>
      </ul>
    </section>
  );
}
