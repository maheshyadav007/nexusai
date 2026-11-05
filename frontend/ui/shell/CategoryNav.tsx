"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { Icon } from "@/ui/icons";
import { useCategories, useSaveCategory, useUpdateCategory } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { Dialog } from "@/ui/primitives/Dialog";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { ActiveMark } from "@/ui/primitives/Motion";
import { t } from "@/ui/strings";
import { categoryHref, customCategories } from "./customMail";

const EDIT_CATEGORIES = "/settings?section=categories";

function NewCategory() {
  const router = useRouter();
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
                router.push(`/mail/category/${encodeURIComponent(name.trim())}`);
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

export function CategoryNavActions({ collapsed }: { collapsed: boolean }) {
  if (collapsed) return null;
  return <div className="flex shrink-0 items-center justify-between px-2 text-sm text-ink-muted"><span>{t("nav.categories")}</span><NewCategory /></div>;
}

/** Folders the person or an agent made. They live in the sidebar beside the fixed ones. */
export function CategoryNav({ collapsed, visibleHrefs }: { collapsed: boolean; visibleHrefs?: ReadonlySet<string> }) {
  const categories = useCategories();
  const pathname = usePathname();
  const router = useRouter();
  const update = useUpdateCategory();
  if (collapsed) return null;
  const hrefOf = categoryHref;
  // A created folder must remain reachable even before any mail is assigned to it.
  const rows = customCategories(categories.data?.categories ?? []).filter((item) => !visibleHrefs || visibleHrefs.has(hrefOf(item.name)));
  return (
    <section aria-label={t("nav.categories")}>
      <ul className="flex flex-col gap-px">
        {rows.map((item) => {
          const href = hrefOf(item.name);
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <li key={item.name} data-testid="nav-category">
              <ContextMenu items={[{ id: "open", label: t("menu.open"), onSelect: () => router.push(href) }, { id: "priority", label: t(item.in_priority ? "menu.leavePriority" : "menu.joinPriority"), onSelect: () => update.mutate({ name: item.name, in_priority: !item.in_priority }) }, { id: "edit", label: t("menu.editCategory"), onSelect: () => router.push(EDIT_CATEGORIES) }]}>
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
      </ul>
    </section>
  );
}
