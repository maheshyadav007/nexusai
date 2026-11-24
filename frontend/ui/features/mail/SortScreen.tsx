"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { command, query } from "@/ui/client/api";
import type { MailCategory, SortSender } from "@/ui/client/contracts.generated";
import { useHomeReady, useLeadName } from "@/ui/client/home";
import { useCategories, useRules } from "@/ui/client/mail";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { SplitReview } from "./SplitReview";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Icon } from "@/ui/icons";
import { IconButton } from "@/ui/primitives/IconButton";
import { Menu, type MenuItem } from "@/ui/primitives/Menu";
import { Popover } from "@/ui/primitives/Popover";
import { BareInput, Pressable } from "@/ui/primitives/Pressable";
import { Progress } from "@/ui/primitives/Progress";
import { Tabs } from "@/ui/primitives/Tabs";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { TextLink } from "@/ui/primitives/TextLink";
import { phrase } from "@/ui/features/settings/RulesSettings";
import { categoryHref } from "@/ui/shell/customMail";
import { EditFolder } from "@/ui/shell/EditFolder";
import { clashOf } from "@/ui/shell/NewFolder";
import { useHiddenFolders, useShownFolders } from "@/ui/shell/hiddenFolders";
import { groupSenders, type SenderGroup } from "./senderGroups";
import { t, tn } from "@/ui/strings";

/** Where each sender stands: its side, and the folder card it sits in. `place` is the folder's
 * exact name: "" is the Inbox itself, "Automated" Kept from the AI's catch-all, and any other
 * name a folder of its own, on that side only. */
interface Choice {
  side: SortSender["side"];
  place: string;
}
type Choices = Record<string, Choice>;
/** One folder card: a side, a folder, the senders in it. */
/** One folder card: a side, a folder, the senders in it. A group is senders in no folder that
 *  share a label, listed greyed like a folder so every one can be seen and ticked into one. */
type Card = { key: string; side: Choice["side"]; place: string; members: SortSender[]; real: boolean; group?: boolean };

// A card's window shows this many of the newest emails of what's picked.
const MAIL_SHOWN = 30;
const AUTOMATED = "Automated";
// How many of each side's biggest get a folder of their own and show in the sidebar, at first.
const FIRST_K = 3;
// Folders the app files by mail headers, before any rule of the person's.
const BY_HEADERS = new Set(["Promotions", "Updates", "Social", "Forums"]);
const fmt = (n: number) => n.toLocaleString();
const keyOf = (name: string) => name.trim().toLocaleLowerCase();
const cardKey = (side: Choice["side"], place: string) => `${side}|${keyOf(place)}`;
const sizeOf = (members: readonly SortSender[]) => members.reduce((n, s) => n + s.count, 0);
// A folder lives on one side, so a sender moved across lands in the other side's "No folder".
const across = (side: Choice["side"]): Choice => (side === "reads" ? { side: "ignores", place: AUTOMATED } : { side: "reads", place: "" });
const noFolder = (place: string) => place === "" || place === AUTOMATED;
const cardName = (place: string) => (noFolder(place) ? t("mail.sort.noFolder") : place);
// How long a sender that just moved stays marked in its new place.
const FLASH_MS = 2400;
// Senders that just moved, marked where they landed.
const Flash = createContext<ReadonlySet<string>>(new Set());
const flashClass = (on: boolean) => (on ? "ring-2 ring-accent-default bg-accent-default/5" : "");
// Every card, for moving a sender with its details instead of dragging it, and the folder modal.
const Cards = createContext<{ all: readonly Card[]; move: (members: readonly SortSender[], to: Choice) => void; flip: (card: Card) => void; open: (card: Card) => void; nameOf: (place: string) => string; makeFolder: (members: readonly SortSender[], side: Choice["side"], name: string) => void }>({ all: [], move: () => undefined, flip: () => undefined, open: () => undefined, nameOf: cardName, makeFolder: () => undefined });
const DRAG = "application/x-nexusai-sender";

/** The sorting page, the same as the Sort lab's: every sender scored, on the side the AI reads
 * or the side it ignores. Setup passes onDone to carry on with its next step; elsewhere it's Today. */
export function SortScreen({ onDone, onBack }: { onDone?: () => void; onBack?: () => void } = {}) {
  const ready = useHomeReady();
  const lead = useLeadName();
  const router = useRouter();
  const client = useQueryClient();
  // Kept current by events: mail.sortChanged when scoring starts, ends or fails, and
  // mail.historyFinished, after which scoring starts by itself.
  const sort = useQuery({ queryKey: ["mail-sort"], queryFn: () => query("mail.sort.get", {}), enabled: ready });
  // Opened again after sorting, from Settings or the sidebar, it looks at the mail afresh.
  const again = !onDone && (sort.data?.state === "done" || sort.data?.state === "skipped");
  const prepare = useMutation({ mutationFn: () => command("mail.sort.prepare", { again }), onSuccess: (data) => client.setQueryData(["mail-sort"], data) });
  const refresh = () => Promise.all(["mail-sort", "categories", "threads", "today"].map((key) => client.invalidateQueries({ queryKey: [key] })));
  // Opened again, what the page shows is the fresh look, while the mail stays sorted.
  const state = again ? sort.data?.review : sort.data?.state;
  // Asked once when the page opens too, so mail or rules that changed since are looked at.
  const asked = useRef(false);
  useEffect(() => {
    if (!state || prepare.isPending) return;
    if (state === "none" || (state === "ready" && !asked.current)) {
      asked.current = true;
      prepare.mutate();
    }
  }, [state, again]);

  if (sort.isError) return <ErrorState title={t("mail.sort.failed")} onRetry={() => void sort.refetch()} />;
  if (!sort.data) return <div className="p-6"><Skeleton className="h-6 w-full" /></div>;
  const back = onBack ? <Button variant="quiet" className="self-start" onClick={onBack}>{t("setup.back")}</Button> : null;
  if (state === "none") return <div className="mx-auto flex max-w-reading flex-col gap-4 p-6">
    <h1 className="font-serif text-title text-ink-primary">{t("mail.sort.title")}</h1>
    <p role="status" className="text-md text-ink-secondary">{t("mail.sort.none")}</p>
    <Skeleton className="h-6 w-full" />
    {back}
  </div>;
  if (state === "preparing") return <div className="mx-auto flex max-w-reading flex-col gap-4 p-6">
    <h1 className="font-serif text-title text-ink-primary">{t("mail.sort.title")}</h1>
    <Progress label={t("mail.sort.preparing", { count: (sort.data.total ?? 0).toLocaleString() })} value={sort.data.done ?? 0} max={Math.max(sort.data.total ?? 0, 1)} />
    <p className="text-sm text-ink-muted">{t("mail.sort.preparing.note")}</p>
    {back}
  </div>;
  if (state === "failed") return <ErrorState title={t("mail.sort.failed")} onRetry={() => prepare.mutate()} />;
  const finished = () => void refresh().then(() => (onDone ? onDone() : router.push("/today")));
  if (state === "done" || state === "skipped") return <div className="p-6"><EmptyState icon="inbox" title={t("mail.sort.title")} description={t(state === "done" ? "mail.sort.done" : "mail.sort.skipped", { name: lead })} {...(onDone ? { action: <Button variant="primary" onClick={onDone}>{t("setup.next")}</Button> } : {})} /></div>;
  return <Sorter senders={sort.data.senders ?? []} owner={sort.data.owner_name ?? ""} total={sort.data.emails ?? 0} calendar={sort.data.calendar ?? 0} alreadySorted={again ? 0 : sort.data.already_sorted ?? 0} lead={lead} onDone={finished} back={back} again={again} />;
}

function Sorter({ senders, owner, total, calendar, alreadySorted, lead, onDone, back, again = false }: { senders: readonly SortSender[]; owner: string; total: number; calendar: number; alreadySorted: number; lead: string; onDone: () => void; back: ReactNode; again?: boolean }) {
  const byCount = [...senders].sort((a, b) => b.count - a.count);
  const [initial] = useState<Choices>(() => {
    // A sender a rule already files starts in its folder, on the side its rule puts it.
    const start: Choices = Object.fromEntries(byCount.map((s) => [s.sender, s.folder ? { side: s.side, place: s.folder } : { side: s.side, place: s.side === "reads" ? "" : s.own ? s.label : AUTOMATED }]));
    // A sender named like a folder that starts on its own joins it, so one tool is one folder.
    const named = new Set(byCount.filter((s) => s.own && !s.folder).map((s) => keyOf(s.label)));
    for (const s of byCount) if (!s.folder && s.side === "ignores" && named.has(keyOf(s.label))) start[s.sender] = { side: "ignores", place: s.label };
    // A first sort gives the AI's side its biggest few folders too, as it does the kept side.
    if (!again) {
      const labels = new Map<string, number>();
      for (const s of byCount) if (!s.folder && s.side === "reads") labels.set(s.label, (labels.get(s.label) ?? 0) + s.count);
      const top = new Set([...labels.entries()].sort((a, b) => b[1] - a[1]).slice(0, FIRST_K).map(([label]) => label));
      for (const s of byCount) if (!s.folder && s.side === "reads" && top.has(s.label)) start[s.sender] = { side: "reads", place: s.label };
    }
    return start;
  });
  const [choices, setChoices] = useState<Choices>(initial);
  // Folders that exist, so a name on the page is known to be one or not.
  const categories = useCategories();
  const existing = new Map((categories.data?.categories ?? []).filter((item) => !item.proposed).map((item) => [keyOf(item.name), item]));
  const real = (side: Choice["side"], place: string) => !noFolder(place) && (existing.get(keyOf(place))?.ai_reads !== false) === (side === "reads") && existing.has(keyOf(place));
  // Whole folders switched to the other home. Saved after the senders, as one move each.
  const [flipped, setFlipped] = useState<Readonly<Record<string, Choice["side"]>>>({});
  // The AI's suggested topic folders, ticked to be made when the page is saved.
  const suggested = (categories.data?.categories ?? []).filter((item) => item.proposed && item.mode === "smart" && item.ai_reads !== false);
  const [declined, setDeclined] = useState<ReadonlySet<string>>(new Set());
  // Existing folders renamed on the page, by their name now: saved after the senders.
  const [renamed, setRenamed] = useState<Readonly<Record<string, string>>>({});
  const shown = (place: string) => renamed[keyOf(place)] ?? cardName(place);
  // The last move: where it came from, said in the column it left until the next one.
  const [moved, setMoved] = useState<{ name: string; from: Choice["side"]; to: string; before: Choices } | null>(null);
  const [flash, setFlash] = useState<ReadonlySet<string>>(new Set());
  useEffect(() => {
    const first = [...flash][0];
    if (!first) return;
    // Only when it landed out of sight, and without animating, so nothing keeps moving under the pointer.
    const landed = document.querySelector(`[data-sort-key="${CSS.escape(first)}"]`);
    const box = landed?.getBoundingClientRect();
    if (landed && box && (box.top < 0 || box.bottom > window.innerHeight)) landed.scrollIntoView({ block: "center" });
    const timer = window.setTimeout(() => setFlash(new Set()), FLASH_MS);
    return () => window.clearTimeout(timer);
  }, [flash]);
  const choice = (s: SortSender) => choices[s.sender] as Choice;
  // Moved or not, each sender is sent as it stands. One the page put in a folder by name goes
  // there, mail and all; a new one kept from the AI is sorted with the rest, under Automated.
  const payload = (s: SortSender) => {
    const now = choice(s);
    const start = initial[s.sender] as Choice;
    // In a folder that moves home whole, the folder takes its senders along afterwards.
    if (flipped[keyOf(now.place)] && keyOf(now.place) === keyOf(start.place)) return { sender: s.sender, side: start.side, own: false, name: "" };
    const same = now.side === start.side && keyOf(now.place) === keyOf(start.place);
    // Kept from the AI in a folder that doesn't exist yet: sorted with the rest, as a folder of its own.
    if (same || (!s.folder && now.side === "ignores" && !real("ignores", now.place))) {
      const own = now.place !== AUTOMATED && now.side === "ignores";
      const name = own ? now.place.slice(0, 60) : "";
      return { sender: s.sender, side: now.side, own, name: name === s.label ? "" : name };
    }
    return { sender: s.sender, side: now.side, own: false, name: "", folder: now.place.slice(0, 64) };
  };
  const apply = useMutation({
    mutationFn: async () => {
      const done = await command("mail.sort.apply", { senders: byCount.map(payload) });
      for (const [key, side] of Object.entries(flipped)) {
        const folder = existing.get(key);
        if (folder) await command("categories.update", { name: folder.name, parent: "", ai_reads: side === "reads" });
      }
      for (const [key, name] of Object.entries(renamed)) {
        const folder = existing.get(key);
        if (folder && folder.name !== name) await command("categories.update", { name: folder.name, new_name: name });
      }
      for (const item of suggested) if (!declined.has(item.name)) await command("categories.decide", { name: item.name, accept: true });
      // What shows in the sidebar, as ticked here.
      const all = [...folders("reads"), ...folders("ignores")];
      const names = (cards: readonly Card[]) => cards.map((card) => shown(card.place).trim()).filter(Boolean);
      await shownFolders.setShown(names(all.filter(ticked)), names(all.filter((card) => !ticked(card))));
      return done;
    },
    onSuccess: onDone,
  });
  const skip = useMutation({ mutationFn: () => command("mail.sort.skip", {}), onSuccess: onDone });

  // The cards, built from where everyone is now. The Inbox and Automated are always there.
  const found = new Map<string, Card>();
  const cardFor = (side: Choice["side"], place: string) => {
    const key = cardKey(side, place);
    if (!found.has(key)) found.set(key, { key, side, place, members: [], real: false });
    return found.get(key) as Card;
  };
  for (const s of byCount) {
    const card = cardFor(choice(s).side, choice(s).place);
    card.members.push(s);
    if (s.folder && keyOf(s.folder) === keyOf(card.place)) card.real = true;
  }
  const inbox = cardFor("reads", "");
  const automated = cardFor("ignores", AUTOMATED);
  const cards = [...found.values()];
  const folders = (side: Choice["side"]) => cards.filter((c) => c.side === side && c !== inbox && c !== automated).sort((a, b) => sizeOf(b.members) - sizeOf(a.members));
  // Every sender in no folder, by label, so each side lists all of its mail, to scroll and tick.
  const groupsOf = (side: Choice["side"]) => [...Map.groupBy((side === "reads" ? inbox : automated).members.filter((s) => !s.folder), (s) => s.label).entries()].map(([label, members]): Card => {
    const group: Card = { key: `${side}|~${keyOf(label)}`, side, place: label, members, real: false, group: true };
    found.set(group.key, group);
    return group;
  });
  const listed = { reads: [...folders("reads"), ...groupsOf("reads")], ignores: [...folders("ignores"), ...groupsOf("ignores")] };
  for (const side of ["reads", "ignores"] as const) listed[side].sort((a, b) => sizeOf(b.members) - sizeOf(a.members));
  // In the sidebar: ticked by hand, or as chosen before, or among the K biggest.
  const { hidden: offSidebar } = useHiddenFolders();
  const ticked = (card: Card) => {
    if (card.group) return false;
    const hand = ticks[card.key];
    if (hand !== undefined) return hand;
    if (shownFolders.chosen && !Object.keys(ticks).length) return ![...offSidebar].some((name) => keyOf(name) === keyOf(card.place));
    return folders(card.side).indexOf(card) < shownK[card.side];
  };
  const tick = (card: Card, on: boolean) => {
    // A group ticked becomes a folder of its own, shown in the sidebar.
    if (card.group && on) {
      move(card.members, { side: card.side, place: card.place });
      setTicks((current) => ({ ...current, [cardKey(card.side, card.place)]: true }));
      return;
    }
    // A folder only this page made, unticked, goes back to being a group in no folder. One that
    // exists stays a folder and only leaves the sidebar.
    if (!on && !card.real && !existing.has(keyOf(card.place))) {
      move(card.members, card.side === "reads" ? { side: "reads", place: "" } : { side: "ignores", place: AUTOMATED });
      return;
    }
    setTicks((current) => ({ ...current, [card.key]: on }));
  };
  // The card as it was when opened, so what moves out of it stays in its window, marked.
  const [modal, setModal] = useState<Card | null>(null);
  const openCard = (card: Card) => setModal({ ...card, members: [...card.members] });
  const reads = byCount.filter((s) => choice(s).side === "reads");
  const ignores = byCount.filter((s) => choice(s).side === "ignores");
  const kept = ignores.reduce((n, s) => n + s.count, 0) + calendar;
  const counted = (emails: number, list: readonly SortSender[]) => `${tn("mail.sort.emailCount", emails)} · ${tn("mail.sort.senderCount", list.length)}`;

  // Every move says where it went and can be undone; nothing is saved until Save.
  const move = (members: readonly SortSender[], to: Choice) => {
    if (!members.length) return;
    const before = Object.fromEntries(members.map((s) => [s.sender, choice(s)]));
    const from = choice(members[0] as SortSender).side;
    setChoices((current) => ({ ...current, ...Object.fromEntries(members.map((s) => [s.sender, to])) }));
    setMoved({ name: members.length === 1 ? (members[0] as SortSender).label : cardName(choice(members[0] as SortSender).place), from, to: cardName(to.place), before });
    setFlash(new Set(members.map((s) => s.sender)));
  };
  const rename = (card: Card, name: string) => setChoices((current) => ({ ...current, ...Object.fromEntries(card.members.map((s) => [s.sender, { side: card.side, place: name.replaceAll("/", " ") }])) }));
  // As many as each side has at first, up to FIRST_K.
  const [shownK] = useState<Record<Choice["side"], number>>(() => {
    const count = (side: Choice["side"]) => new Set(byCount.filter((s) => initial[s.sender]?.side === side && !noFolder(initial[s.sender]?.place ?? "")).map((s) => keyOf(initial[s.sender]?.place ?? ""))).size;
    return { reads: Math.min(FIRST_K, count("reads")), ignores: Math.min(FIRST_K, count("ignores")) };
  });
  // Folders ticked or unticked by hand; the rest follow K, the biggest shown.
  const [ticks, setTicks] = useState<Record<string, boolean>>({});
  const shownFolders = useShownFolders();
  // A whole folder to the other home: one that exists moves as itself; one only on this page
  // goes with its name. The "No folder" cards swap.
  const flip = (card: Card) => {
    const side = card.side === "reads" ? "ignores" : "reads";
    if (noFolder(card.place) || card.group) { move(card.members, across(card.side)); return; }
    const key = keyOf(card.place);
    if (real(card.side, card.place) || flipped[key]) setFlipped((current) => {
      const next = { ...current };
      const was = existing.get(key);
      if (was && (was.ai_reads !== false) === (side === "reads")) delete next[key];
      else next[key] = side;
      return next;
    });
    move(card.members, { side, place: card.place });
  };
  // What's different from how the page opened, by where it went, each with its own undo.
  const changed = [...Map.groupBy(byCount.filter((s) => cardKey(choice(s).side, choice(s).place) !== cardKey((initial[s.sender] as Choice).side, (initial[s.sender] as Choice).place)), (s) => cardKey(choice(s).side, choice(s).place)).values()];
  const undo = (members: readonly SortSender[]) => setChoices((current) => ({ ...current, ...Object.fromEntries(members.map((s) => [s.sender, initial[s.sender] as Choice])) }));
  const movedNote = (side: Choice["side"]) =>
    moved && moved.from === side ? (
      <div data-testid="sort-moved-note" role="status" className="flex items-center justify-between gap-3 rounded-md border border-dashed border-line-strong p-3 text-sm text-ink-muted">
        <span className="min-w-0">{t("mail.sort.movedHere", { name: moved.name, side: moved.to })}</span>
        <Button variant="quiet" className="py-px" onClick={() => { setChoices((current) => ({ ...current, ...moved.before })); setMoved(null); }}>{t("mail.sort.undo")}</Button>
      </div>
    ) : null;
  const other = (card: Card) => (!noFolder(card.place) && !card.group ? found.get(cardKey(card.side === "reads" ? "ignores" : "reads", card.place))?.members.length ?? 0 : 0);
  // A name is free when no folder anywhere has it, whatever its case, on this page or saved.
  const clash = (card: Card, name: string) => {
    const clean = name.trim().replace(/\s+/g, " ");
    const own = keyOf(card.place);
    const saved = clashOf(clean, (categories.data?.categories ?? []).filter((item) => keyOf(item.name) !== own && !renamed[keyOf(item.name)]));
    if (saved) return saved;
    const taken = cards.find((c) => c !== card && !c.group && !noFolder(c.place) && keyOf(shown(c.place)) === keyOf(clean));
    return taken ? t("folder.new.taken", { name: shown(taken.place), where: t(taken.side === "reads" ? "folder.new.inInbox" : "folder.new.inKept") }) : null;
  };
  // Saved folders keep their senders and change their name on Save; one this page made moves them.
  const renameCard = (card: Card, name: string) => {
    const clean = name.trim().replace(/\s+/g, " ").slice(0, 60);
    if (existing.has(keyOf(card.place))) { setRenamed((current) => ({ ...current, [keyOf(card.place)]: clean })); return; }
    const on = ticked(card);
    rename(card, clean);
    setTicks((current) => ({ ...current, [cardKey(card.side, clean)]: on }));
  };
  // Where a whole card can go: the other side as a folder of its own, or into any other folder.
  const movesFor = (card: Card): MenuItem[] => {
    const other = card.side === "reads" ? "ignores" : "reads";
    const sideName = (side: Choice["side"]) => t(side === "reads" ? "mail.sort.reads" : "mail.sort.ignores");
    const own: MenuItem = { id: "flip", label: noFolder(card.place) ? `${sideName(other)} · ${t("mail.sort.noFolder")}` : t("mail.sort.move.own", { side: sideName(other) }), onSelect: () => flip(card) };
    const into = cards.filter((c) => !c.group && c.key !== cardKey(other, card.place)).sort((a, b) => (a.side === b.side ? 0 : a.side === card.side ? 1 : -1));
    // Where it is now is listed too, marked and not to be chosen, so the menu shows every place.
    return [own, ...into.map((c): MenuItem => c === card ? { id: c.key, label: t("mail.sort.move.here", { place: `${sideName(c.side)} · ${shown(c.place)}` }), disabled: true } : { id: c.key, label: `${sideName(c.side)} · ${shown(c.place)}`, onSelect: () => move(card.members, { side: c.side, place: c.place }) })];
  };
  // A folder of their own for some senders, on either side, under a name no folder has yet,
  // shown in the sidebar like the others the page made.
  const makeFolder = (members: readonly SortSender[], side: Choice["side"], base: string) => {
    const clean = base.trim().replace(/\s+/g, " ").replaceAll("/", " ").slice(0, 56) || t("mail.sort.noFolder");
    const used = new Set([...(categories.data?.categories ?? []).map((item) => keyOf(item.name)), ...cards.filter((c) => !c.group).map((c) => keyOf(shown(c.place)))]);
    let name = clean;
    for (let n = 2; used.has(keyOf(name)) || clashOf(name, []); n += 1) name = `${clean} ${n}`;
    move(members, { side, place: name });
    setTicks((current) => ({ ...current, [cardKey(side, name)]: true }));
  };
  const show = (card: Card) => <FolderCard key={card.key} card={card} name={shown(card.place)} also={other(card)} moves={movesFor(card)} {...(noFolder(card.place) ? {} : { tick: { on: ticked(card), set: (on: boolean) => tick(card, on) } })} {...(noFolder(card.place) || card.group ? {} : { rename: { clash: (name: string) => clash(card, name), save: (name: string) => renameCard(card, name) } })} />;
  const choiceOf = (s: SortSender) => choice(s);

  return <div className="flex min-h-full flex-1 flex-col">
    <div className="flex flex-1 flex-col gap-5 px-5 py-6 md:px-6">
      {again ? <SplitReview /> : null}
      <header className="flex flex-col gap-2">
        <h1 className="flex flex-wrap items-baseline gap-2 font-serif text-title text-ink-primary">
          {t("mail.sort.title")}
          <span className="flex items-center gap-1 font-sans text-md tabular-nums text-ink-muted">
            {tn("mail.sort.emailCount", total)}
            <Popover label={t("mail.sort.how")} trigger={<IconButton icon="info" label={t("mail.sort.how")} />}>
              <ul className="flex max-w-reading flex-col gap-2 text-sm text-ink-secondary">
                <li>{t("mail.sort.how.score")}</li>
                <li>{t("mail.sort.how.threshold")}</li>
                <li>{t("mail.sort.how.through")}</li>
              </ul>
            </Popover>
          </span>
        </h1>
        <p className="text-sm text-ink-muted">{t("mail.sort.ticks")}</p>
        {alreadySorted > 0 ? <p className="text-sm tabular-nums text-ink-muted">{t("mail.sort.alreadySorted", { count: fmt(alreadySorted) })}</p> : null}
      </header>
      <Flash.Provider value={flash}>
      <Cards.Provider value={{ all: cards, move, flip, open: openCard, nameOf: shown, makeFolder }}>
      <Choosing.Provider value={choiceOf}>
      <div className="grid items-start gap-5 lg:grid-cols-2 lg:gap-7">
        <Column title={t("mail.sort.reads")} reads count={counted(total - kept, reads)}>
          {movedNote("reads")}
          {suggested.length ? <Suggested items={suggested} declined={declined} onChange={(name, on) => setDeclined((current) => { const next = new Set(current); if (on) next.delete(name); else next.add(name); return next; })} /> : null}
          <TickedCards cards={listed.reads} ticked={ticked} render={show} />
          {show(inbox)}
        </Column>
        <Column title={t("mail.sort.ignores")} count={counted(kept, ignores)}>
          {movedNote("ignores")}
          <TickedCards cards={listed.ignores} ticked={ticked} render={show} />
          {show(automated)}
        </Column>
      </div>
      {modal ? <FolderModal card={modal} existing={existing.get(keyOf(modal.place))} onClose={() => setModal(null)} /> : null}
      </Choosing.Provider>
      </Cards.Provider>
      </Flash.Provider>
    </div>
    <footer className="sticky bottom-0 flex flex-wrap items-center justify-between gap-3 border-t border-line-subtle bg-surface-raised px-5 py-3 md:px-6">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-sm text-ink-muted">{again ? t("mail.sort.save.note") : t("mail.sort.finish.note", { name: lead })}</p>
        {apply.isError || skip.isError ? <p role="alert" className="text-sm text-status-danger">{(apply.error ?? skip.error)?.message}</p> : null}
      </div>
      <div className="flex items-center gap-2">
        {back}
        {changed.length ? (
          <Popover label={t("mail.sort.changes.title")} trigger={<Button variant="quiet" data-testid="sort-changes">{tn("mail.sort.changes", changed.length)}</Button>}>
            <div className="flex flex-col gap-2">
              <p className="text-md font-medium text-ink-primary">{t("mail.sort.changes.title")}</p>
              <ul className="flex flex-col gap-1">
                {changed.map((members) => {
                  const first = members[0] as SortSender;
                  return (
                    <li key={first.sender} className="flex items-center justify-between gap-3 text-md">
                      <span className="min-w-0 truncate">{t("mail.sort.change", { name: members.length === 1 ? first.label : tn("mail.sort.senderCount", members.length), side: cardName(choice(first).place) })}</span>
                      <Button variant="quiet" className="py-px" onClick={() => undo(members)}>{t("mail.sort.undo")}</Button>
                    </li>
                  );
                })}
              </ul>
            </div>
          </Popover>
        ) : null}
        {again ? null : <Button variant="quiet" loading={skip.isPending} disabled={apply.isPending} onClick={() => skip.mutate()}>{t("mail.sort.skip")}</Button>}
        <Button variant="primary" loading={apply.isPending} disabled={skip.isPending} onClick={() => apply.mutate()}>{t(again ? "mail.sort.save" : "mail.sort.finish")}</Button>
      </div>
    </footer>
  </div>;
}

// Where a sender is now, for its own switch and its folder picker.
const Choosing = createContext<(s: SortSender) => Choice>(() => ({ side: "reads", place: "" }));

function Column({ title, reads = false, count, children }: { title: string; reads?: boolean; count: string; children: ReactNode }) {
  return <section aria-label={title} className="flex min-w-0 flex-col gap-3">
    {/* The side in its own colour, so a folder's card needs no mark of its side. */}
    <header className={`flex flex-wrap items-center gap-2 rounded-lg px-4 py-3 ${reads ? "bg-accent-default/10 text-accent-default" : "bg-surface-sunken text-ink-secondary"}`}>
      <Icon name={reads ? "readByAi" : "keptFromAi"} className="h-5 w-5" />
      <h2 className="flex-1 text-lg font-medium">{title}</h2>
      <span className="text-md font-medium tabular-nums">{count}</span>
    </header>
    {children}
  </section>;
}

// Each side lists this many cards, the ticked first, until opened; its No folder card is always shown.
const CARDS_SHOWN = 6;

/** The ticked folders, the ones the sidebar shows, then the rest, greyed, to tick: the first few,
 *  and the others behind Show more. */
function TickedCards({ cards, ticked, render }: { cards: readonly Card[]; ticked: (card: Card) => boolean; render: (card: Card) => ReactNode }) {
  const [all, setAll] = useState(false);
  const ordered = [...cards.filter(ticked), ...cards.filter((card) => !ticked(card))];
  const rest = ordered.length - CARDS_SHOWN;
  return <>
    {(all ? ordered : ordered.slice(0, CARDS_SHOWN)).map(render)}
    {rest > 0 ? <Button variant="quiet" className="self-start" aria-expanded={all} onClick={() => setAll(!all)}>{all ? t("mail.sort.fewer") : tn("mail.sort.moreCards", rest)}</Button> : null}
  </>;
}

/** One folder: a tick for the sidebar, its name with a pencil to rename it, its size under it,
 *  and Move to. Its emails, senders and rule open in a window over the page.
 *  Senders can be dropped on it from any other card. */
function FolderCard({ card, name, also, moves, tick, rename }: { card: Card; name: string; also: number; moves: readonly MenuItem[]; tick?: { on: boolean; set: (on: boolean) => void }; rename?: { clash: (name: string) => string | null; save: (name: string) => void } }) {
  const { all, move, open } = useContext(Cards);
  const flashing = useContext(Flash);
  const [over, setOver] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const landed = card.members.some((s) => flashing.has(s.sender));
  const catchAll = noFolder(card.place);
  const greyed = tick !== undefined && !tick.on;
  const to: Choice = { side: card.side, place: card.place };
  const problem = draft === null ? null : draft.trim() ? rename?.clash(draft) ?? null : t("mail.sort.rename.empty");
  // Enter or leaving the name saves it when it's free; Escape, or a name that isn't, keeps the old one.
  const finish = (keep: boolean) => {
    if (draft !== null && keep && !problem && draft.trim() !== name) rename?.save(draft);
    setDraft(null);
  };
  return <div
    data-testid="sort-folder"
    data-side={card.side}
    data-folder={card.place}
    data-sort-key={card.members[0]?.sender}
    onDragOver={(event) => { if (event.dataTransfer.types.includes(DRAG)) { event.preventDefault(); setOver(true); } }}
    onDragLeave={() => setOver(false)}
    onDrop={(event) => { setOver(false); const sender = all.flatMap((c) => c.members).find((s) => s.sender === event.dataTransfer.getData(DRAG)); if (sender) move([sender], to); }}
    data-ticked={tick ? String(tick.on) : undefined}
    data-group={card.group ? "true" : undefined}
    className={`flex flex-col gap-2 rounded-lg border p-3 transition-shadow duration-normal ${greyed ? "bg-transparent" : "bg-surface-raised"} ${catchAll ? "border-dashed border-line-strong" : "border-line-subtle"} ${over ? "ring-2 ring-accent-default" : ""} ${flashClass(landed)}`}>
    <div data-testid="sort-folder-head" className="flex items-center gap-3">
      {tick ? <Checkbox hideLabel label={t("mail.sort.tick", { name })} checked={tick.on} onChange={tick.set} /> : null}
      <Icon name="folder" className={`h-4 w-4 shrink-0 ${greyed ? "text-ink-faint" : card.side === "reads" ? "text-accent-default" : "text-ink-muted"}`} />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="flex min-w-0 items-center gap-1">
          {draft === null ? <>
            <Pressable aria-label={t("mail.sort.open", { name })} onClick={() => open(card)} className={`min-w-0 truncate rounded-sm text-left text-md hover:underline ${greyed ? "text-ink-muted" : "font-medium text-ink-primary"}`}>{name}</Pressable>
            {rename ? <IconButton icon="edit" label={t("mail.sort.rename", { name })} className="shrink-0" onClick={() => setDraft(name)} /> : null}
          </> : (
            // Edited in place: the name stays where it is, underlined, with no box around it.
            <BareInput
              autoFocus
              aria-label={t("mail.sort.categoryName")}
              aria-invalid={problem ? true : undefined}
              value={draft}
              maxLength={60}
              onChange={(event) => setDraft(event.target.value)}
              onBlur={() => finish(true)}
              onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); if (!problem) finish(true); } else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); finish(false); } }}
              className={`min-w-0 flex-1 border-0 border-b p-0 text-md font-medium outline-none ${problem ? "border-status-danger" : "border-accent-default"}`}
            />
          )}
        </span>
        {/* One line under the name, so editing never moves the card: what it holds, or how the edit is going. */}
        {draft === null ? (
          <span className="text-sm tabular-nums text-ink-muted">
            {`${tn("mail.sort.senderCount", card.members.length)} · ${tn("mail.sort.emailCount", sizeOf(card.members))}`}
          </span>
        ) : <span role={problem ? "alert" : undefined} className={`text-sm ${problem ? "text-status-danger" : "text-ink-muted"}`}>{problem ? t("mail.sort.rename.problem", { problem, name }) : t("mail.sort.rename.hint", { name })}</span>}
      </div>
      {card.members.length ? <MoveMenu name={name} items={moves} /> : null}
    </div>
    {card.place === AUTOMATED ? <p className="text-sm text-ink-muted">{t("mail.sort.automated.sub")}</p> : card.place === "" ? <p className="text-sm text-ink-muted">{t("mail.sort.noFolder.reads")}</p> : null}
    {/* The count only when it isn't every sender, which the line above already says. */}
    {card.real && card.members.some((s) => s.folder) ? <p className="text-sm text-ink-muted">{card.members.every((s) => s.folder) ? t("mail.sort.filed.all") : t("mail.sort.filed", { senders: tn("mail.sort.senderCount", card.members.filter((s) => s.folder).length) })}</p> : null}
    {also ? <p className="text-sm text-ink-muted">{t("mail.sort.also", { senders: tn("mail.sort.senderCount", also), side: t(card.side === "reads" ? "mail.sort.ignores" : "mail.sort.reads") })}</p> : null}
    {!card.members.length ? <p className="rounded-md border border-dashed border-line-subtle p-3 text-sm text-ink-muted">{t("mail.sort.empty")}</p> : null}
  </div>;
}

/** A card's senders and their mail, in a window over the page: on the left its senders in groups,
 *  each group and sender with Move to; on the right the emails or the rules of what's picked,
 *  whichever tab is chosen staying chosen from one pick to the next. The list is the one the card
 *  had when it opened, so a group moved away stays here, marked. */
function FolderModal({ card, existing, onClose }: { card: Card; existing: MailCategory | undefined; onClose: () => void }) {
  const now = useContext(Choosing);
  const { nameOf } = useContext(Cards);
  const name = nameOf(card.place);
  const groups = useMemo(() => groupSenders(card.members), [card]);
  const [picked, setPicked] = useState<Picked>(null);
  const [tab, setTab] = useState<"emails" | "rules">("emails");
  const [opened, setOpened] = useState<ReadonlySet<string>>(() => new Set(groups.slice(0, 1).filter((group) => group.members.length > 1).map((group) => group.key)));
  const [editing, setEditing] = useState(false);
  const read = card.members.filter((s) => now(s).side === "reads");
  const side = read.length === card.members.length ? t("mail.sort.reads") : read.length === 0 ? t("mail.sort.ignores") : t("mail.sort.modal.mixed", { read: fmt(read.length), hidden: fmt(card.members.length - read.length) });
  const real = Boolean(existing) && !noFolder(card.place);
  const toggle = (key: string) => setOpened((current) => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  const members = picked && "group" in picked ? picked.group.members : picked ? [picked.sender] : card.members;
  const rules = useFolderRules(card, existing, members);
  return <Dialog shape="glass" title={name} description={t("mail.sort.modal.summary", { senders: tn("mail.sort.senderCount", card.members.length), emails: tn("mail.sort.emailCount", sizeOf(card.members)), side })} open onOpenChange={(open) => { if (!open) onClose(); }}>
    <div data-testid="sort-folder-modal" className="grid min-h-0 flex-1 overflow-y-auto border-t border-line-subtle md:grid-cols-2 md:overflow-hidden">
      <ul aria-label={t("mail.sort.modal.senders", { name })} className="flex min-h-0 flex-col md:overflow-y-auto md:border-r md:border-line-subtle">
        {card.members.length ? groups.map((group) => <GroupRow key={group.key} group={group} open={opened.has(group.key)} onToggle={() => toggle(group.key)} picked={picked} onPick={setPicked} />) : <li className="p-3 text-sm text-ink-muted">{t("mail.sort.empty")}</li>}
      </ul>
      <section className="min-h-0 bg-surface-sunken px-4 pb-4 md:overflow-y-auto">
        <Tabs label={t("mail.sort.modal.show")} value={tab} onValueChange={(value) => setTab(value as "emails" | "rules")} tabs={[
          { value: "emails", label: t("mail.sort.modal.emails"), content: <div className="flex flex-col gap-3">
            {picked && "group" in picked ? <PickedMail title={picked.group.name} count={picked.group.count} members={picked.group.members} />
              : picked ? <PickedMail title={picked.sender.sender} count={picked.sender.count} members={[picked.sender]} sender={picked.sender} />
              : <FolderEmails card={card} real={real} />}
          </div> },
          { value: "rules", label: t("mail.sort.modal.rules", { count: fmt(rules.count) }), content: <FolderRules card={card} rules={rules} picked={picked} existing={existing} onEdit={() => setEditing(true)} /> },
        ]} />
      </section>
    </div>
    {editing && existing ? <EditFolder category={existing} open onOpenChange={setEditing} onRenamed={() => setEditing(false)} /> : null}
  </Dialog>;
}

// What the right side of a card's window is about: a group, a sender, or the whole card.
type Picked = { group: SenderGroup } | { sender: SortSender } | null;

/** Where senders can go: a folder of their own on either side, or any folder or No folder,
 *  the other side first. Where all of them are now is listed, marked, and can't be chosen. */
function useMoves(members: readonly SortSender[], name: string): MenuItem[] {
  const { all, move, nameOf, makeFolder } = useContext(Cards);
  const now = useContext(Choosing);
  const here = new Set(members.map((s) => cardKey(now(s).side, now(s).place)));
  const side = members[0] ? now(members[0]).side : "reads";
  const sideName = (of: Choice["side"]) => t(of === "reads" ? "mail.sort.reads" : "mail.sort.ignores");
  const sides: Choice["side"][] = side === "reads" ? ["ignores", "reads"] : ["reads", "ignores"];
  const own = sides.map((to): MenuItem => ({ id: `own-${to}`, label: t("mail.sort.move.ownNamed", { side: sideName(to), name }), onSelect: () => makeFolder(members, to, name) }));
  const into = all
    .filter((c) => !c.group)
    .sort((a, b) => (a.side === b.side ? 0 : a.side === side ? 1 : -1))
    .map((c): MenuItem => here.size === 1 && here.has(c.key)
      ? { id: c.key, label: t("mail.sort.move.here", { place: `${sideName(c.side)} · ${nameOf(c.place)}` }), disabled: true }
      : { id: c.key, label: `${sideName(c.side)} · ${nameOf(c.place)}`, onSelect: () => move(members.filter((s) => cardKey(now(s).side, now(s).place) !== c.key), { side: c.side, place: c.place }) });
  return [...own, ...into];
}

/** The one Move to button, on folder cards and on the rows of a card's window alike. */
function MoveMenu({ name, items }: { name: string; items: readonly MenuItem[] }) {
  return <Menu label={t("mail.sort.move", { name })} items={items} trigger={<Button variant="quiet" aria-label={t("mail.sort.move", { name })} className="shrink-0 gap-1 border border-line-subtle px-2 py-px text-sm">{t("mail.sort.moveButton")}<Icon name="chevronDown" className="h-3 w-3" /></Button>} />;
}

/** One group: its name, size and Move to, and its senders under it when opened. A group of one
 *  is just that sender. A group split across sides says so under its name. */
function GroupRow({ group, open, onToggle, picked, onPick }: { group: SenderGroup; open: boolean; onToggle: () => void; picked: Picked; onPick: (picked: Picked) => void }) {
  const now = useContext(Choosing);
  const moves = useMoves(group.members, group.name);
  if (group.members.length === 1) return <SenderLine sender={group.members[0] as SortSender} picked={picked} onPick={onPick} />;
  const read = group.members.filter((s) => now(s).side === "reads").length;
  const side = read === group.members.length ? "reads" : read === 0 ? "ignores" : undefined;
  const on = Boolean(picked && "group" in picked && picked.group.key === group.key);
  const sub = side ? tn("mail.sort.senderCount", group.members.length) : t("mail.sort.modal.split", { read: fmt(read), count: fmt(group.members.length) });
  return <li data-testid="sort-group" data-side={side ?? "mixed"} className="border-b border-line-subtle">
    <div className={`flex items-center gap-2 px-3 py-2 ${on ? "bg-surface-sunken" : ""}`}>
      <IconButton icon={open ? "chevronDown" : "chevronRight"} label={t(open ? "mail.sort.modal.close" : "mail.sort.modal.open", { name: group.name })} aria-expanded={open} onClick={onToggle} />
      <Pressable aria-pressed={on} onClick={() => onPick({ group })} className="flex min-w-0 flex-1 flex-col rounded-md text-left">
        <span className="break-words text-md font-medium text-ink-primary">{group.name}</span>
        <span className="text-sm text-ink-muted">{sub}</span>
      </Pressable>
      <span className="shrink-0 text-md tabular-nums text-ink-secondary">{fmt(group.count)}</span>
      <MoveMenu name={group.name} items={moves} />
    </div>
    {open ? <ul className="flex flex-col pb-1 pl-7">{group.members.map((s) => <SenderLine key={s.sender} sender={s} picked={picked} onPick={onPick} />)}</ul> : null}
  </li>;
}

/** One sender: the whole address, how many emails, and Move to. A press shows its mail. */
function SenderLine({ sender: s, picked, onPick }: { sender: SortSender; picked: Picked; onPick: (picked: Picked) => void }) {
  const now = useContext(Choosing)(s);
  const flashing = useContext(Flash);
  const { nameOf } = useContext(Cards);
  // Its own folder is named after it: its label, or, where the label is the folder it's leaving,
  // the address before the @, so "PLM" doesn't make a second "PLM".
  const moves = useMoves([s], keyOf(s.label) === keyOf(nameOf(now.place)) ? s.sender.split("@")[0] ?? s.label : s.label);
  const on = Boolean(picked && "sender" in picked && picked.sender.sender === s.sender);
  return <li data-testid="sort-sender" data-side={now.side} data-sort-key={s.sender} className={`flex items-center gap-2 border-b border-line-subtle px-3 py-2 last:border-b-0 ${on ? "bg-surface-sunken" : ""} ${flashClass(flashing.has(s.sender))}`}>
    <Pressable aria-pressed={on} onClick={() => onPick({ sender: s })} className="min-w-0 flex-1 rounded-md text-left">
      <span className="break-all text-md text-ink-primary">{s.sender}</span>
    </Pressable>
    <span className="shrink-0 text-md tabular-nums text-ink-secondary">{fmt(s.count)}</span>
    <MoveMenu name={s.sender} items={moves} />
  </li>;
}

/** The newest emails of a group or one sender. One sender also says why it's on its side and
 *  what kinds of mail it sends. */
function PickedMail({ title, count, members, sender }: { title: string; count: number; members: readonly SortSender[]; sender?: SortSender }) {
  const rows = members.flatMap((s) => s.emails.map((email, index) => ({ key: `${s.sender}-${index}`, from: email.sender_name || s.sender, subject: email.subject, when: email.when }))).slice(0, MAIL_SHOWN);
  const reasons = sender ? [why(sender), sender.kept ? t("mail.sort.kept", { why: sender.kept.toLocaleLowerCase() }) : ""].filter(Boolean) : [];
  return <>
    <div className="flex flex-col gap-1">
      <h3 className="break-all text-md font-medium text-ink-primary">{title}</h3>
      <p className="text-sm tabular-nums text-ink-muted">{t("mail.sort.modal.newest", { shown: fmt(rows.length), emails: tn("mail.sort.emailCount", count) })}</p>
      {reasons.length ? <p className="text-sm text-ink-secondary">{reasons.join(" · ")}</p> : null}
    </div>
    <MailRows rows={rows} />
    {sender?.kinds?.length ? <SenderKinds sender={sender} /> : null}
  </>;
}

function MailRows({ rows }: { rows: readonly { key: string; from: string; subject: string; when: string }[] }) {
  if (!rows.length) return <p className="text-sm text-ink-muted">{t("mail.sort.modal.none")}</p>;
  return <ul className="flex flex-col divide-y divide-line-subtle rounded-md border border-line-subtle bg-surface-raised">
    {/* The sender above and the whole subject below, so the subject has the full width. */}
    {rows.map((row) => <li key={row.key} data-testid="sort-folder-email" className="flex flex-col gap-1 px-3 py-2">
      <span className="flex items-baseline justify-between gap-3 text-sm text-ink-muted">
        <span className="truncate">{row.from}</span>
        <span className="shrink-0 tabular-nums">{row.when}</span>
      </span>
      <span className="break-words text-md text-ink-primary">{row.subject || t("mail.sort.noSubject")}</span>
    </li>)}
  </ul>;
}

/** The newest emails in it: from the folder itself once it exists, else from its senders. */
function FolderEmails({ card, real }: { card: Card; real: boolean }) {
  const ready = useHomeReady();
  const filed = useQuery({ queryKey: ["threads", "sort-folder", card.place], queryFn: () => query("threads.list", { folder: "all", category: card.place, limit: MAIL_SHOWN }), enabled: ready && real });
  const rows = real
    ? (filed.data?.threads ?? []).map((row) => ({ key: String(row.id), from: row.sender_name ?? "", subject: row.subject, when: new Date(row.last_date).toLocaleDateString(undefined, { day: "numeric", month: "short" }) }))
    : card.members.flatMap((s) => s.emails.map((email, index) => ({ key: `${s.sender}-${index}`, from: email.sender_name || s.sender, subject: email.subject, when: email.when }))).slice(0, MAIL_SHOWN);
  if (real && filed.isPending) return <Skeleton className="h-6 w-full" />;
  return <>
    <p className="text-sm text-ink-muted">{t("mail.sort.modal.pick")}</p>
    <MailRows rows={rows} />
    {real ? <TextLink href={categoryHref(card.place)}>{t("mail.sort.modal.openFolder", { name: card.place })}</TextLink> : null}
  </>;
}

// One condition of a rule, as a chip: what it looks at, then the value in bold.
type Chip = { label: string; value?: string };
// The rules of one sender, or of any sender when a rule names none.
type RuleGroup = { who: string; rules: Chip[][] };

/** The rules for some of a card's senders: the folder's own once it exists, else those Save will
 *  write, one per kind of mail a hidden sender sends, or one for all it sends. By sender. */
function useFolderRules(card: Card, existing: MailCategory | undefined, members: readonly SortSender[]): { groups: RuleGroup[]; count: number; narrowed: boolean } {
  const saved = useRules().data?.rules ?? [];
  const reads = card.side === "reads";
  if (noFolder(card.place)) return { groups: [], count: 0, narrowed: false };
  const mine = new Set(members.map((s) => s.sender.toLowerCase()));
  const groups = new Map<string, Chip[][]>();
  const add = (who: string, chips: Chip[]) => groups.set(who, [...(groups.get(who) ?? []), chips]);
  let narrowed = false;
  if (existing) {
    for (const rule of saved) {
      if (keyOf(rule.actions.category ?? "") !== keyOf(card.place)) continue;
      const from = rule.conditions.find((c) => (c.field === "sender_exact" || c.field === "sender") && (c.value ?? "").includes("@"));
      if (from && members !== card.members && !mine.has((from.value ?? "").toLowerCase())) continue;
      const rest = rule.conditions.filter((c) => c !== from);
      if (rest.length) narrowed = true;
      add(from?.value ?? t("mail.sort.rule.anySender"), rest.length ? rest.map((c) => ({ label: phrase(c) })) : [{ label: t("mail.sort.rule.any") }]);
    }
  } else {
    for (const s of members) {
      if (!reads && s.kinds?.length) {
        narrowed = true;
        for (const kind of s.kinds) add(s.sender, [...(kind.tag ? [{ label: t("mail.sort.rule.tag"), value: `[${kind.tag}]` }] : []), ...(kind.words.length ? [{ label: t("mail.sort.rule.words"), value: kind.words.join(" ") }] : [])]);
      } else add(s.sender, [{ label: t("mail.sort.rule.any") }]);
    }
  }
  const list = [...groups.entries()].map(([who, rules]) => ({ who, rules }));
  return { groups: list, count: list.reduce((n, group) => n + group.rules.length, 0), narrowed };
}

/** The rules as rules: each sender once, its rules as chips under it, then the notes as bullets. */
function FolderRules({ card, rules, picked, existing, onEdit }: { card: Card; rules: { groups: RuleGroup[]; narrowed: boolean }; picked: Picked; existing: MailCategory | undefined; onEdit: () => void }) {
  const { nameOf } = useContext(Cards);
  const reads = card.side === "reads";
  const where = t("mail.sort.rule.where", { name: nameOf(card.place), side: t(reads ? "mail.sort.rule.read" : "mail.sort.rule.hiddenFrom") });
  const lead = noFolder(card.place) ? t("mail.sort.rule.lead.none")
    : card.group ? t("mail.sort.rule.lead.group")
    : !existing ? `${t("mail.sort.rule.lead.will")} ${where}`
    : rules.groups.length ? `${t("mail.sort.rule.lead.rule")} ${where}`
    : existing.mode === "smart" ? t("mail.sort.rule.lead.ai", { description: existing.description || existing.name })
    : BY_HEADERS.has(existing.name) ? t("mail.sort.rule.lead.headers")
    : t("mail.sort.rule.lead.empty");
  const notes = [rules.narrowed ? t("mail.sort.rule.rest") : "", noFolder(card.place) ? "" : t(reads ? "mail.sort.rule.reads" : "mail.sort.rule.hidden")].filter(Boolean);
  return <div data-testid="sort-rules" className="flex flex-col gap-4">
    <p className="text-sm text-ink-secondary">{lead}</p>
    {picked && !rules.groups.length && !noFolder(card.place) ? <p className="text-sm text-ink-muted">{t("mail.sort.rule.noneHere")}</p> : null}
    {rules.groups.map((group) => <div key={group.who} className="flex flex-col gap-1">
      <h3 className="break-all text-sm font-medium text-ink-primary">{group.who}</h3>
      {group.rules.map((chips, index) => <div key={index} data-testid="sort-rule" className="flex flex-wrap items-center gap-1 rounded-md border border-line-subtle bg-surface-raised px-3 py-2">
        {chips.map((chip, n) => <span key={n} className="flex items-center gap-1">
          {n ? <span className="text-sm text-ink-faint">{t("mail.sort.rule.and")}</span> : null}
          <span className="rounded-sm bg-surface-sunken px-2 py-px text-sm text-ink-secondary">{chip.label}{chip.value ? <b className="ml-1 font-medium text-ink-primary">{chip.value}</b> : null}</span>
        </span>)}
      </div>)}
    </div>)}
    {notes.length ? <ul className="flex list-disc flex-col gap-1 rounded-md bg-surface-raised py-2 pl-6 pr-3 text-sm text-ink-secondary">{notes.map((note) => <li key={note}>{note}</li>)}</ul> : null}
    {existing && !noFolder(card.place) ? <Button className="self-start" onClick={onEdit}>{t("mail.sort.rule.edit")}</Button> : null}
  </div>;
}

function why(s: SortSender): string {
  const parts: string[] = [];
  if (s.repeats >= 0.5) parts.push(t("mail.sort.why.repeats", { pct: Math.round(s.repeats * 100) }));
  if (s.bulk >= 0.5) parts.push(t("mail.sort.why.bulk"));
  if (s.one_way) parts.push(t("mail.sort.why.oneWay"));
  if (s.no_reply) parts.push(t("mail.sort.why.noReply"));
  return parts.join(" · ");
}

/** The kinds of mail a sender sends, each with how many, and what fits none: that mail is out
 * of the ordinary, so the AI reads it even when the sender is hidden. */
function SenderKinds({ sender: s }: { sender: SortSender }) {
  const kinds = s.kinds ?? [];
  return <div data-testid="sort-kinds" className="flex flex-col gap-1 text-sm">
    <p className="text-ink-muted">{tn("mail.sort.kinds", kinds.length)}</p>
    <ul className="flex flex-col gap-1">
      {kinds.map((kind) => <li key={`${kind.tag}|${kind.words.join(" ")}`} className="flex items-baseline justify-between gap-3">
        <span className="min-w-0 text-ink-primary">{[kind.tag ? `[${kind.tag}]` : "", ...kind.words].filter(Boolean).join(" ")}</span>
        <span className="shrink-0 tabular-nums text-ink-muted">{fmt(kind.count)}</span>
      </li>)}
    </ul>
    {s.odd ? <p className="text-ink-muted">{t("mail.sort.odd", { count: fmt(s.odd), example: s.odd_examples?.[0] ?? "" })}</p> : null}
  </div>;
}

/** The AI's suggested topic folders for the side it reads, ticked to be made on Save. */
function Suggested({ items, declined, onChange }: { items: readonly MailCategory[]; declined: ReadonlySet<string>; onChange: (name: string, on: boolean) => void }) {
  return <div data-testid="sort-suggested" className="flex flex-col gap-2 rounded-lg border border-dashed border-line-strong p-3">
    <p className="text-md font-medium text-ink-primary">{t("mail.sort.suggested")}</p>
    <ul className="flex flex-col gap-1">
      {items.map((item) => <li key={item.name}><Checkbox label={item.description && item.description !== item.name ? `${item.name} · ${item.description}` : item.name} checked={!declined.has(item.name)} onChange={(on) => onChange(item.name, on)} /></li>)}
    </ul>
    <p className="text-sm text-ink-muted">{t("mail.sort.suggested.note")}</p>
  </div>;
}
