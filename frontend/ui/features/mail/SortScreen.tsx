"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { command, query } from "@/ui/client/api";
import type { SortGroup } from "@/ui/client/contracts.generated";
import { useHomeReady, useLeadName } from "@/ui/client/home";
import { Icon, type IconName } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Input } from "@/ui/primitives/Input";
import { Pressable, RowButton } from "@/ui/primitives/Pressable";
import { Progress } from "@/ui/primitives/Progress";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";

type SortFolder = SortGroup["folder"];

/** Where each group of mail goes before the AI reads any of it. The folder is the one choice
 * that matters: the AI reads the Inbox and ignores Automated and Calendar. */
const FOLDERS: readonly { id: SortFolder; icon: IconName; reads: boolean }[] = [
  { id: "inbox", icon: "inbox", reads: true },
  { id: "automated", icon: "folder", reads: false },
  { id: "calendar", icon: "date", reads: false },
];
// Smaller categories fold away, so the big decisions are what shows.
const SMALL = 5;

interface Category extends SortGroup {
  name: string;
  place: SortFolder;
  mergedInto: string;
}

const FOLDER_NAMES = { inbox: "mail.sort.folder.inbox", automated: "mail.sort.folder.automated", calendar: "mail.sort.folder.calendar" } as const;
const folderName = (id: SortFolder) => t(FOLDER_NAMES[id]);
const reads = (id: SortFolder) => FOLDERS.find((folder) => folder.id === id)?.reads ?? true;

export function SortScreen() {
  const ready = useHomeReady();
  const lead = useLeadName();
  const router = useRouter();
  const client = useQueryClient();
  const sort = useQuery({ queryKey: ["mail-sort"], queryFn: () => query("mail.sort.get", {}), enabled: ready, refetchInterval: (state) => (state.state.data?.state === "preparing" ? 1500 : false) });
  const prepare = useMutation({ mutationFn: () => command("mail.sort.prepare", {}), onSuccess: (data) => client.setQueryData(["mail-sort"], data) });
  const refresh = () => Promise.all([client.invalidateQueries({ queryKey: ["mail-sort"] }), client.invalidateQueries({ queryKey: ["categories"] }), client.invalidateQueries({ queryKey: ["threads"] }), client.invalidateQueries({ queryKey: ["today"] })]);
  const state = sort.data?.state;
  useEffect(() => {
    if (state === "none" && !prepare.isPending) prepare.mutate();
  }, [state]);

  if (sort.isError) return <ErrorState title={t("mail.sort.failed")} onRetry={() => void sort.refetch()} />;
  if (!sort.data || state === "none") return <div className="p-6"><Skeleton className="h-6 w-full" /></div>;
  if (state === "preparing") return <div className="mx-auto flex max-w-reading flex-col gap-4 p-6">
    <h1 className="font-serif text-title text-ink-primary">{t("mail.sort.title")}</h1>
    <Progress label={t("mail.sort.preparing", { count: (sort.data.total ?? 0).toLocaleString() })} value={sort.data.done ?? 0} max={Math.max(sort.data.total ?? 0, 1)} />
    <p className="text-sm text-ink-muted">{t("mail.sort.preparing.note")}</p>
  </div>;
  if (state === "failed") return <ErrorState title={t("mail.sort.failed")} onRetry={() => prepare.mutate()} />;
  if (state === "done" || state === "skipped") return <div className="p-6"><EmptyState icon="inbox" title={t("mail.sort.title")} description={t(state === "done" ? "mail.sort.done" : "mail.sort.skipped", { name: lead })} /></div>;
  return <Sorter groups={sort.data.groups ?? []} owner={sort.data.owner_name ?? ""} emails={sort.data.emails ?? 0} conversations={sort.data.conversations ?? 0} lead={lead} onDone={() => void refresh().then(() => router.push("/today"))} />;
}

function Sorter({ groups, owner, emails, conversations, lead, onDone }: { groups: SortGroup[]; owner: string; emails: number; conversations: number; lead: string; onDone: () => void }) {
  const [cats, setCats] = useState<Record<string, Category>>(() => Object.fromEntries(groups.map((group) => [group.id, { ...group, name: group.label, place: group.folder, mergedInto: "" }])));
  const [selected, setSelected] = useState<string>(() => [...groups].filter((g) => g.folder === "automated").sort((a, b) => b.count - a.count)[0]?.id ?? groups[0]?.id ?? "");
  const [opened, setOpened] = useState<Record<string, boolean>>({});
  const [undo, setUndo] = useState<{ cat: Category; target: Category } | null>(null);
  const apply = useMutation({
    mutationFn: () => command("mail.sort.apply", { choices: Object.values(cats).map((cat) => ({ id: cat.id, name: cat.name === cat.label ? "" : cat.name.slice(0, 60), folder: cat.place, merged_into: cat.mergedInto })) }),
    onSuccess: onDone,
  });
  const skip = useMutation({ mutationFn: () => command("mail.sort.skip", {}), onSuccess: onDone });
  const live = useMemo(() => Object.values(cats).filter((cat) => !cat.mergedInto), [cats]);
  const kept = live.filter((cat) => !reads(cat.place)).reduce((n, cat) => n + cat.count - cat.names_you, 0);
  const change = (id: string, patch: Partial<Category>) => setCats((current) => ({ ...current, [id]: { ...current[id]!, ...patch } }));
  const merge = (cat: Category, targetId: string) => {
    const target = cats[targetId];
    if (!target) return;
    setCats((current) => ({
      ...current,
      [cat.id]: { ...cat, mergedInto: target.id },
      [target.id]: { ...target, count: target.count + cat.count, names_you: target.names_you + cat.names_you, emails: [...target.emails, ...cat.emails].slice(0, 20), senders: [...new Set([...target.senders, ...cat.senders])] },
    }));
    setUndo({ cat, target });
    setSelected(target.id);
  };
  const undoMerge = () => {
    if (!undo) return;
    setCats((current) => ({ ...current, [undo.cat.id]: undo.cat, [undo.target.id]: undo.target }));
    setSelected(undo.cat.id);
    setUndo(null);
  };
  const cat = cats[selected];

  return <div className="flex min-h-full flex-1 flex-col md:flex-row">
    <nav aria-label={t("mail.sort.folders")} className="flex shrink-0 flex-col border-b border-line-subtle bg-surface-raised md:w-sidebar md:border-b-0 md:border-r">
      <div className="flex flex-col gap-1 px-5 pb-3 pt-5">
        <h1 className="font-serif text-title text-ink-primary">{t("mail.sort.title")}</h1>
        <p className="text-sm tabular-nums text-ink-muted">{owner ? `${owner} · ` : ""}{t("mail.sort.summary", { emails: emails.toLocaleString(), kept: kept.toLocaleString() })}</p>
      </div>
      <div className="flex flex-col gap-4 overflow-y-auto px-3 pb-3 md:flex-1">
        {FOLDERS.map((folder) => <FolderBlock key={folder.id} folder={folder} cats={live} selected={selected} opened={opened} conversations={folder.id === "inbox" ? conversations : 0}
          onToggle={(key) => setOpened((current) => ({ ...current, [key]: !current[key] }))} onSelect={(id) => { setSelected(id); setUndo(null); }} />)}
      </div>
      <div className="flex flex-col gap-2 border-t border-line-subtle p-4">
        <Button variant="primary" loading={apply.isPending} disabled={skip.isPending} onClick={() => apply.mutate()}>{t("mail.sort.finish")}</Button>
        <p className="text-xs text-ink-muted">{t("mail.sort.finish.note", { name: lead })}</p>
        <Button variant="quiet" loading={skip.isPending} disabled={apply.isPending} onClick={() => skip.mutate()}>{t("mail.sort.skip")}</Button>
        {apply.isError || skip.isError ? <p role="alert" className="text-sm text-status-danger">{(apply.error ?? skip.error)?.message}</p> : null}
      </div>
    </nav>
    <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-6 md:px-6">
      {cat ? <CategoryView key={cat.id} cat={cat} others={live.filter((other) => other.id !== cat.id)} undo={undo} onUndo={undoMerge}
        onRename={(name) => change(cat.id, { name })} onMove={(place) => { change(cat.id, { place }); setUndo(null); }} onMerge={(target) => merge(cat, target)} />
        : <p className="text-md text-ink-muted">{t("mail.sort.pick")}</p>}
    </main>
  </div>;
}

function FolderBlock({ folder, cats, selected, opened, conversations, onToggle, onSelect }: { folder: (typeof FOLDERS)[number]; cats: Category[]; selected: string; opened: Record<string, boolean>; conversations: number; onToggle: (key: string) => void; onSelect: (id: string) => void }) {
  const inside = cats.filter((cat) => cat.place === folder.id).sort((a, b) => b.count - a.count);
  // Senders the engine left alone stay folded until opened, or until someone changes them.
  const waiting = inside.filter((cat) => cat.unsorted && cat.name === cat.label && cat.id !== selected);
  const shown = inside.filter((cat) => !waiting.includes(cat));
  const big = shown.filter((cat) => cat.count >= SMALL || cat.id === selected);
  const small = shown.filter((cat) => !big.includes(cat));
  const total = inside.reduce((n, cat) => n + cat.count, 0) + conversations;
  const sum = (list: Category[]) => list.reduce((n, cat) => n + cat.count, 0).toLocaleString();
  return <section className="flex flex-col">
    <div className="flex items-center justify-between gap-2 px-2 py-2">
      <span className="flex items-center gap-2 text-md font-medium text-ink-primary"><Icon name={folder.icon} />{folderName(folder.id)}<span className="text-sm font-normal tabular-nums text-ink-muted">{total.toLocaleString()}</span></span>
      <span className={`rounded-full px-2 py-px text-xs font-medium ${folder.reads ? "bg-status-success text-accent-on" : "bg-surface-sunken text-ink-secondary"}`}>{t(folder.reads ? "mail.sort.reads" : "mail.sort.ignores")}</span>
    </div>
    {big.map((cat) => <CategoryRow key={cat.id} cat={cat} selected={cat.id === selected} onSelect={onSelect} />)}
    {small.length ? <>
      {opened[folder.id] ? small.map((cat) => <CategoryRow key={cat.id} cat={cat} selected={false} onSelect={onSelect} />) : null}
      <Pressable onClick={() => onToggle(folder.id)} className="rounded-md py-1 pl-6 text-left text-sm text-accent-primary">{opened[folder.id] ? t("mail.sort.fewer") : t("mail.sort.more", { count: small.length, emails: sum(small) })}</Pressable>
    </> : null}
    {waiting.length ? <>
      <Pressable onClick={() => onToggle("waiting")} className="rounded-md py-1 pl-6 text-left text-sm text-accent-primary">{opened.waiting ? t("mail.sort.unsorted.hide") : t("mail.sort.unsorted", { count: waiting.length, emails: sum(waiting) })}</Pressable>
      {opened.waiting ? waiting.map((cat) => <CategoryRow key={cat.id} cat={cat} selected={false} onSelect={onSelect} />) : null}
    </> : null}
    {conversations > 0 ? <div className="flex justify-between py-2 pl-6 pr-2 text-sm text-ink-muted"><span>{t("mail.sort.conversations")}</span><span className="tabular-nums">{conversations.toLocaleString()}</span></div> : null}
  </section>;
}

function CategoryRow({ cat, selected, onSelect }: { cat: Category; selected: boolean; onSelect: (id: string) => void }) {
  return <RowButton aria-current={selected || undefined} onClick={() => onSelect(cat.id)}
    className={`justify-between py-2 pl-6 pr-2 text-sm ${selected ? "bg-surface-sunken font-medium text-ink-primary" : "text-ink-secondary"}`}>
    <span className="min-w-0 truncate">{cat.name}{cat.unsorted && cat.name === cat.label && cat.place === "inbox" ? <span className="text-xs text-ink-muted"> · {t("mail.sort.unsorted.tag")}</span> : null}</span>
    <span className="shrink-0 tabular-nums">{cat.count.toLocaleString()}</span>
  </RowButton>;
}

function CategoryView({ cat, others, undo, onUndo, onRename, onMove, onMerge }: { cat: Category; others: Category[]; undo: { cat: Category; target: Category } | null; onUndo: () => void; onRename: (name: string) => void; onMove: (place: SortFolder) => void; onMerge: (target: string) => void }) {
  const senders = cat.senders.length > 2 ? t("mail.sort.senders", { count: cat.senders.length }) : cat.senders.join(", ");
  const reason = cat.unsorted ? t("mail.sort.unsorted.reason") : cat.reason ? `${cat.reason.replace(/[^.]$/, "$&.")}` : "";
  return <>
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm text-ink-muted">
        {t("mail.sort.category")}
        <Input value={cat.name} maxLength={60} onChange={(event) => onRename(event.target.value)} className="font-serif text-title" />
      </label>
      <div className="flex w-full flex-col gap-1 text-sm text-ink-muted sm:w-rail-wide md:w-popover">
        <span id="sort-folder">{t("mail.sort.folder")}</span>
        <Select describedBy="sort-folder" label={t("mail.sort.folder")} value={cat.place} onChange={(value) => onMove(value as SortFolder)}
          options={FOLDERS.map((folder) => ({ value: folder.id, label: t(folder.reads ? "mail.sort.option.reads" : "mail.sort.option.ignores", { folder: folderName(folder.id) }) }))} />
      </div>
    </div>
    <p className="text-sm text-ink-muted">{t("mail.sort.from", { count: cat.count.toLocaleString(), senders })} {reason}</p>
    {undo ? <p className="text-sm text-ink-muted">{t("mail.sort.merged", { name: undo.cat.name, target: undo.target.name })} <Pressable onClick={onUndo} className="rounded-md text-accent-primary">{t("mail.sort.undo")}</Pressable></p> : null}
    <ul className="overflow-hidden rounded-lg border border-line-subtle bg-surface-raised">
      {cat.emails.map((email, index) => {
        const you = email.names_you && !reads(cat.place);
        return <li key={`${email.subject}-${index}`} className={`flex items-baseline justify-between gap-4 border-b border-line-subtle px-4 py-3 text-sm last:border-b-0 ${you ? "bg-surface-sunken" : ""}`}>
          <span className="min-w-0 truncate"><span className="font-medium text-ink-primary">{email.subject || "—"}</span> <span className={you ? "text-status-success" : "text-ink-muted"}>· {you ? t("mail.sort.namesYou") : `${email.sender_name}${email.snippet ? ` — ${email.snippet}` : ""}`}</span></span>
          <span className="shrink-0 tabular-nums text-ink-muted">{email.when}</span>
        </li>;
      })}
    </ul>
    <div className="flex flex-wrap items-center gap-3">
      <span id="sort-merge" className="text-sm text-ink-muted">{t("mail.sort.merge")}</span>
      <div className="w-full sm:w-popover">
        <Select describedBy="sort-merge" label={t("mail.sort.merge")} placeholder={t("mail.sort.merge.placeholder")} onChange={onMerge}
          options={[...others].sort((a, b) => a.name.localeCompare(b.name)).map((other) => ({ value: other.id, label: t("mail.sort.merge.option", { name: other.name, folder: folderName(other.place), count: other.count.toLocaleString() }) }))} />
      </div>
      {cat.count > cat.emails.length ? <span className="text-sm text-ink-muted">{t("mail.sort.showing", { shown: cat.emails.length, count: cat.count.toLocaleString() })}</span> : null}
    </div>
  </>;
}
