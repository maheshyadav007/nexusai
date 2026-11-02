"use client";

import type { MessageView, ThreadRow } from "@/ui/client/contracts.generated";
import { useAddCategory, useAddToFolder, useCategories, useMailFolders, useRemoveFromFolder, useRemoveThreadCategory } from "@/ui/client/mail";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { IconButton } from "@/ui/primitives/IconButton";
import { Menu } from "@/ui/primitives/Menu";
import { t, type StringKey } from "@/ui/strings";

// Filing on this computer or from an archive file isn't a folder anyone can remove it from here.
const NOT_ON_SERVER = /^(local|pst):/;
// All Mail holds everything on Gmail, so it says nothing about where this email was filed.
const HIDDEN_ROLES = new Set(["all"]);
const ROLE_NAMES: Readonly<Record<string, StringKey>> = { inbox: "nav.inbox", sent: "nav.sent", drafts: "nav.drafts", archive: "nav.archive", trash: "nav.trash", junk: "nav.junk" };

const labelOf = (name: string, role: string) => {
  const known = ROLE_NAMES[role];
  return known ? t(known) : (name.split("/").pop() ?? name);
};

function Chip({ label, onRemove, removeLabel }: { label: string; onRemove?: (() => void) | undefined; removeLabel: string }) {
  return (
    <li data-testid="filed-in" className="flex items-center gap-1 rounded-md bg-surface-sunken py-px pl-2 pr-1 text-sm text-ink-secondary">
      <Icon name="folder" className="h-3 w-3 shrink-0 text-ink-muted" />
      <span className="max-w-popover truncate">{label}</span>
      {onRemove ? <IconButton icon="close" label={removeLabel} tooltip={false} className="p-px" onClick={onRemove} /> : <span className="w-1" />}
    </li>
  );
}

/** Every folder and category a conversation is in, which can be several, and a way to add more. */
export function ThreadFiling({ thread, messages }: { thread: ThreadRow; messages: readonly MessageView[] }) {
  const folders = useMailFolders();
  const categories = useCategories();
  const addFolder = useAddToFolder();
  const removeFolder = useRemoveFromFolder();
  const addCategory = useAddCategory();
  const removeCategory = useRemoveThreadCategory();
  const here = new Map<string, string>();
  for (const message of messages) for (const place of message.folders ?? []) if (!HIDDEN_ROLES.has(place.role)) here.set(place.name, place.role);
  const onServer = [...here.keys()].filter((name) => !NOT_ON_SERVER.test(name));
  const named = [...(thread.category ? [thread.category] : []), ...(thread.extra_categories ?? [])];
  const moreFolders = (folders.data?.folders ?? []).filter((row) => row.role === "other" && !here.has(row.name));
  const moreCategories = (categories.data?.categories ?? []).filter((row) => !row.proposed && !named.includes(row.name));
  const items = [
    ...moreFolders.map((row) => ({ id: `folder-${row.name}`, label: row.name, icon: "folder" as const, onSelect: () => addFolder.mutate({ id: thread.id, folder: row.name }) })),
    ...moreCategories.map((row) => ({ id: `category-${row.name}`, label: row.name, icon: "folder" as const, onSelect: () => addCategory.mutate({ id: thread.id, name: row.name }) })),
  ];
  return (
    <ul aria-label={t("mail.filedIn")} className="flex flex-wrap items-center gap-1">
      {[...here.entries()].map(([name, role]) => {
        const label = labelOf(name, role);
        // An email can't lose its last folder this way, which is what Delete is for.
        const removable = onServer.length > 1 && !NOT_ON_SERVER.test(name);
        return <Chip key={name} label={label} removeLabel={t("mail.removeFromFolder", { name: label })} onRemove={removable ? () => removeFolder.mutate({ id: thread.id, folder: name }) : undefined} />;
      })}
      {named.map((name) => <Chip key={`c-${name}`} label={name} removeLabel={t("mail.removeFromFolder", { name })} onRemove={() => removeCategory.mutate({ id: thread.id, name })} />)}
      {items.length ? (
        <li>
          <Menu trigger={<Button variant="quiet" className="py-px">{t("mail.addToFolder")}</Button>} items={items} />
        </li>
      ) : null}
    </ul>
  );
}
