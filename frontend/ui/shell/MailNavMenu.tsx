"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { command } from "@/ui/client/api";
import type { MailCategory, MarkFolderRead } from "@/ui/client/contracts.generated";
import { useGetMoreFromFolder, useRemoveCategory, useUpdateCategory } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Dialog } from "@/ui/primitives/Dialog";
import type { MenuItem } from "@/ui/primitives/Menu";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";
import { keptFromAi } from "./customMail";
import { EditFolder } from "./EditFolder";
import { NewFolder } from "./NewFolder";
import { useHiddenFolders } from "./hiddenFolders";

export const categorySettingsHref = (name: string) => `/settings?section=categories&category=${encodeURIComponent(name)}`;

/** Only offer supported operations; every write reports failure and can be retried. */
export function MailNavMenu({ href, scope, category, home, moreFolder, children }: { href: string; scope: MarkFolderRead; category?: MailCategory; home?: "reads" | "kept"; moreFolder?: string; children: ReactNode }) {
  const router = useRouter();
  const client = useQueryClient();
  const toast = useToast();
  const update = useUpdateCategory();
  const remove = useRemoveCategory();
  const more = useGetMoreFromFolder();
  const [removing, setRemoving] = useState(false);
  const [sorting, setSorting] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [editing, setEditing] = useState(false);
  const [making, setMaking] = useState(false);
  const { hidden, setHidden } = useHiddenFolders();
  const [newName, setNewName] = useState("");
  const failed = (error: Error) => toast({ title: error.message, tone: "danger" });
  const read = useMutation({ mutationFn: () => command("mail.markFolderRead", scope), onSuccess: () => { void client.invalidateQueries({ queryKey: ["threads"] }); void client.invalidateQueries({ queryKey: ["mail-folders"] }); void client.invalidateQueries({ queryKey: ["categories"] }); void client.invalidateQueries({ queryKey: ["thread"] }); toast({ title: t("menu.folderReadDone") }); }, onError: failed });
  const sort = useMutation({ mutationFn: (confirm: boolean) => command("categories.sort", { name: category!.name, confirm }), onError: failed });
  const busy = update.isPending || remove.isPending || read.isPending || sort.isPending || more.isPending;
  const items: MenuItem[] = [
    { id: "open", label: t("menu.open"), icon: "folder", onSelect: () => router.push(href) },
    { id: "read", label: t("menu.markFolderRead"), icon: "check", disabled: busy, onSelect: () => read.mutate() },
  ];
  if (moreFolder) items.push({ id: "more", label: t("mail.folder.getRest"), icon: "background", disabled: busy, onSelect: () => more.mutate({ folder: moreFolder }, { onError: failed }) });
  // Both homes have the same four: what's here, and making or sorting what goes in them.
  if (home) items.push(
    { id: "newFolder", label: t("menu.newFolder"), icon: "add", onSelect: () => setMaking(true) },
    { id: "sortSenders", label: t("menu.sortSenders"), icon: "customize", onSelect: () => router.push("/mail/sort") },
  );
  const kept = category ? keptFromAi(category) : false;
  if (category) items.push(
    { id: "editFolder", label: t("menu.editFolder"), icon: "edit", disabled: busy, onSelect: () => setEditing(true) },
    { id: "rename", label: t("menu.renameCategory"), disabled: busy, onSelect: () => { setNewName(category.name); setRenaming(true); } },
    { id: "hide", label: t(hidden.has(category.name) ? "menu.showFolder" : "menu.hideFolder"), icon: hidden.has(category.name) ? "eye" : "eyeOff", onSelect: () => setHidden(category.name, !hidden.has(category.name)) },
    { id: "priority", label: t(category.in_priority ? "menu.leavePriority" : "menu.joinPriority"), icon: "priority", disabled: busy, onSelect: () => update.mutate({ name: category.name, in_priority: !category.in_priority }, { onError: failed, onSuccess: () => toast({ title: t("menu.categoryUpdated") }) }) },
    // The AI doesn't read what's kept from it, so it can't sort it either.
    { id: "mode", label: t(category.mode === "exact" ? "menu.useSmart" : "menu.useExact"), disabled: busy || (kept && category.mode === "exact"), onSelect: () => { if (category.mode !== "exact") { router.push(categorySettingsHref(category.name)); return; } update.mutate({ name: category.name, mode: "smart" }, { onError: failed, onSuccess: () => toast({ title: t("menu.categoryUpdated") }) }); } },
    { id: "edit", label: t("menu.categorySettings"), icon: "settings", onSelect: () => router.push(categorySettingsHref(category.name)) },
    { id: "sort", label: t("menu.sortOlder"), disabled: busy, onSelect: () => { sort.reset(); setSorting(true); sort.mutate(false); } },
    { id: "newInside", label: t("menu.newFolderInside"), icon: "add", onSelect: () => setMaking(true) },
    { id: "remove", label: t("menu.removeCategory"), icon: "trash", danger: true, disabled: busy, onSelect: () => setRemoving(true) },
  );
  return <>
    <ContextMenu items={items}>{children}</ContextMenu>
    {home || category ? <NewFolder open={making} onOpenChange={setMaking} inside={category ? `folder:${category.name}` : home === "kept" ? "home:kept" : "home:reads"} /> : null}
    {category ? <>
      <EditFolder category={category} open={editing} onOpenChange={setEditing} onRenamed={(name) => { toast({ title: t("menu.categoryUpdated") }); if (window.location.pathname === href || window.location.pathname.startsWith(`${href}/`)) router.push(`/mail/category/${encodeURIComponent(name)}`); }} />
      <Dialog title={t("menu.renameCategory")} open={renaming} onOpenChange={setRenaming}>
        <form className="flex flex-col gap-4" onSubmit={(event) => {
          event.preventDefault();
          if (!newName.trim() || newName.trim() === category.name || update.isPending) return;
          update.mutate({ name: category.name, new_name: newName.trim() }, { onError: failed, onSuccess: () => {
            setRenaming(false);
            toast({ title: t("menu.categoryUpdated") });
            if (window.location.pathname === href || window.location.pathname.startsWith(`${href}/`)) router.push(`/mail/category/${encodeURIComponent(newName.trim())}`);
          } });
        }}>
          <Field label={t("categories.name")}>{({ invalid, ...control }) => <Input invalid={invalid} value={newName} maxLength={64} onChange={(event) => setNewName(event.target.value)} {...control} />}</Field>
          <Button type="submit" disabled={!newName.trim() || newName.trim() === category.name} loading={update.isPending}>{t("settings.save")}</Button>
        </form>
      </Dialog>
      <Dialog title={t("categories.remove")} description={t("menu.removeCategoryDescription", { name: category.name })} open={removing} onOpenChange={setRemoving}>
        <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate(category.name, { onError: failed, onSuccess: () => { setRemoving(false); toast({ title: t("menu.categoryRemoved") }); if (window.location.pathname === href || window.location.pathname.startsWith(`${href}/`)) router.push(category.parent ? `/mail/category/${encodeURIComponent(category.parent)}` : kept ? "/mail/kept" : "/mail/inbox"); } })}>{t("categories.remove")}</Button>
      </Dialog>
      <Dialog title={t("categories.sort")} open={sorting} onOpenChange={setSorting}>
        {sort.data ? <p className="mb-4">{t("categories.sort.cost", { count: sort.data.conversations, tokens: sort.data.estimated_tokens })}</p> : null}
        {sort.isError ? <Button onClick={() => sort.mutate(false)}>{t("error.retry")}</Button> : <Button disabled={!sort.data} loading={sort.isPending} onClick={() => sort.mutate(true, { onSuccess: () => { setSorting(false); toast({ title: t("menu.sortDone") }); } })}>{t("categories.sort.confirm")}</Button>}
      </Dialog>
    </> : null}
  </>;
}
