"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { command } from "@/ui/client/api";
import type { MailCategory, MarkFolderRead } from "@/ui/client/contracts.generated";
import { useGetMoreFromFolder, useRemoveCategory, useUpdateCategory } from "@/ui/client/mail";
import { PRIORITY_SHOWS, PRIORITY_SHOWS_DEFAULT, type PriorityShow, useSettings, useUpdateSettings } from "@/ui/client/settings";
import { Button } from "@/ui/primitives/Button";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { Dialog } from "@/ui/primitives/Dialog";
import type { MenuItem } from "@/ui/primitives/Menu";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";
import { AUTOMATED, CALENDAR, keptFromAi } from "./customMail";
import { EditFolder } from "./EditFolder";
import { NewFolder } from "./NewFolder";
import { useHiddenFolders } from "./hiddenFolders";

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
  const [editing, setEditing] = useState(false);
  const [making, setMaking] = useState(false);
  const { hidden, setHidden } = useHiddenFolders();
  const failed = (error: Error) => toast({ title: error.message, tone: "danger" });
  const read = useMutation({ mutationFn: () => command("mail.markFolderRead", scope), onSuccess: () => { void client.invalidateQueries({ queryKey: ["threads"] }); void client.invalidateQueries({ queryKey: ["mail-folders"] }); void client.invalidateQueries({ queryKey: ["categories"] }); void client.invalidateQueries({ queryKey: ["thread"] }); toast({ title: t("menu.folderReadDone") }); }, onError: failed });
  const sort = useMutation({ mutationFn: (confirm: boolean) => command("categories.sort", { name: category!.name, confirm }), onError: failed });
  const settings = useSettings();
  const updateSettings = useUpdateSettings();
  const busy = update.isPending || remove.isPending || read.isPending || sort.isPending || more.isPending;
  const view = "folder" in scope ? scope.folder : undefined;
  // Sent and Drafts have nothing to mark read or change.
  const items: MenuItem[] = !category && !home && (view === "sent" || view === "drafts") ? [] : [
    { id: "read", label: t("menu.markFolderRead"), icon: "check", disabled: busy, onSelect: () => read.mutate() },
  ];
  if (moreFolder) items.push({ id: "more", label: t("mail.folder.getRest"), icon: "background", disabled: busy, onSelect: () => more.mutate({ folder: moreFolder }, { onError: failed }) });
  if (view === "priority" && !category) {
    const shows = new Set<PriorityShow>(settings.data?.priority_shows ?? []);
    const choose = (next: readonly PriorityShow[]) => updateSettings.mutate({ priority_shows: [...next] }, { onError: failed, onSuccess: () => { void client.invalidateQueries({ queryKey: ["threads"] }); void client.invalidateQueries({ queryKey: ["mail-folders"] }); } });
    const option = (id: PriorityShow, divider = false): MenuItem => ({ id, label: t(`priority.show.${id}`), checked: shows.has(id), divider, disabled: !settings.data, onSelect: () => choose(PRIORITY_SHOWS.filter((one) => (one === id ? !shows.has(id) : shows.has(one)))) });
    items.push({ id: "shows", label: t("menu.priorityShows"), icon: "customize", divider: true, items: [
      { id: "matters", label: t("menu.priorityShows.matters"), heading: true },
      option("waiting_on_you"), option("waiting_on_others"),
      { id: "also", label: t("menu.priorityShows.also"), heading: true, divider: true },
      option("important"), option("folders"), option("unfiled"),
      { id: "reset", label: t("menu.priorityShows.reset"), divider: true, onSelect: () => choose(PRIORITY_SHOWS_DEFAULT) },
    ] });
  }
  // Both homes: making folders, and choosing where each sender's mail goes.
  if (home) items.push(
    { id: "newFolder", label: t("menu.newFolder"), icon: "add", divider: true, onSelect: () => setMaking(true) },
    { id: "sortSenders", label: t("menu.sortSenders"), icon: "customize", onSelect: () => router.push("/mail/sort") },
  );
  const kept = category ? keptFromAi(category) : false;
  // Automated and Calendar are the app's own: they can be shown or hidden, not changed.
  const builtIn = category ? [AUTOMATED, CALENDAR].includes(category.name) : false;
  if (category && !builtIn) items.push(
    { id: "newInside", label: t("menu.newFolderInside"), icon: "add", divider: true, onSelect: () => setMaking(true) },
    { id: "editFolder", label: t("menu.editFolder"), icon: "edit", disabled: busy, onSelect: () => setEditing(true) },
    { id: "sort", label: t("menu.sortOlder"), icon: "inbox", disabled: busy, onSelect: () => { sort.reset(); setSorting(true); sort.mutate(false); } },
  );
  if (category) items.push(
    { id: "priority", label: t("menu.showInPriority"), icon: "priority", checked: category.in_priority, divider: true, disabled: busy, onSelect: () => update.mutate({ name: category.name, in_priority: !category.in_priority }, { onError: failed, onSuccess: () => toast({ title: t("menu.categoryUpdated") }) }) },
    { id: "hide", label: t(hidden.has(category.name) ? "menu.showFolder" : "menu.hideFolder"), icon: hidden.has(category.name) ? "eye" : "eyeOff", onSelect: () => setHidden(category.name, !hidden.has(category.name)) },
  );
  if (category && !builtIn) items.push({ id: "remove", label: t("menu.removeCategory"), icon: "trash", danger: true, divider: true, disabled: busy, onSelect: () => setRemoving(true) });
  return <>
    <ContextMenu items={items}>{children}</ContextMenu>
    {home || category ? <NewFolder open={making} onOpenChange={setMaking} inside={category ? `folder:${category.name}` : home === "kept" ? "home:kept" : "home:reads"} /> : null}
    {category ? <>
      <EditFolder category={category} open={editing} onOpenChange={setEditing} onRenamed={(name) => { toast({ title: t("menu.categoryUpdated") }); if (window.location.pathname === href || window.location.pathname.startsWith(`${href}/`)) router.push(`/mail/category/${encodeURIComponent(name)}`); }} />
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
