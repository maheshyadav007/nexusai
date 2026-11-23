"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { command, query } from "@/ui/client/api";
import type { MailCategory, SortSender } from "@/ui/client/contracts.generated";
import { useHomeReady, useLeadName } from "@/ui/client/home";
import { useCategories } from "@/ui/client/mail";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { SplitReview } from "./SplitReview";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Icon } from "@/ui/icons";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Popover } from "@/ui/primitives/Popover";
import { Pressable } from "@/ui/primitives/Pressable";
import { Progress } from "@/ui/primitives/Progress";
import { Segmented } from "@/ui/primitives/Segmented";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
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
type Card = { key: string; side: Choice["side"]; place: string; members: SortSender[]; real: boolean };

// Each side opens with this many folders; the rest are a click away.
const CARDS_SHOWN = 8;
// Lists show this many senders until opened, so the biggest are what shows.
const SHOWN = 8;
const AUTOMATED = "Automated";
const BIGGEST = [0, 3, 5, 10, 20];
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
// Every card, for moving a sender with its details instead of dragging it.
const Cards = createContext<{ all: readonly Card[]; move: (members: readonly SortSender[], to: Choice) => void; flip: (card: Card) => void }>({ all: [], move: () => undefined, flip: () => undefined });
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
  // Folders made on the page, empty until a sender is put in one.
  const [made, setMade] = useState<readonly Choice[]>([]);
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
      for (const item of suggested) if (!declined.has(item.name)) await command("categories.decide", { name: item.name, accept: true });
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
  for (const c of made) cardFor(c.side, c.place).real = true;
  for (const s of byCount) {
    const card = cardFor(choice(s).side, choice(s).place);
    card.members.push(s);
    if (s.folder && keyOf(s.folder) === keyOf(card.place)) card.real = true;
  }
  const inbox = cardFor("reads", "");
  const automated = cardFor("ignores", AUTOMATED);
  const cards = [...found.values()];
  const folders = (side: Choice["side"]) => cards.filter((c) => c.side === side && c !== inbox && c !== automated).sort((a, b) => sizeOf(b.members) - sizeOf(a.members));
  const reads = byCount.filter((s) => choice(s).side === "reads");
  const ignores = byCount.filter((s) => choice(s).side === "ignores");
  const kept = ignores.reduce((n, s) => n + s.count - s.reach, 0) + calendar;
  const counted = (list: readonly SortSender[]) => `${tn("mail.sort.senderCount", list.length)} · ${tn("mail.sort.emailCount", sizeOf(list))}`;

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
  // Own folders for the biggest kept senders that have none yet; the rest go into Automated.
  const fresh = (s: SortSender) => !s.folder && choice(s).side === "ignores" && !real("ignores", choice(s).place) && !flipped[keyOf(choice(s).place)] && !made.some((c) => cardKey(c.side, c.place) === cardKey("ignores", choice(s).place));
  // Every folder kept from the AI counts, the ones already there and the ones about to be.
  const keptFolders = new Set(byCount.filter((s) => choice(s).side === "ignores" && choice(s).place !== AUTOMATED).map((s) => keyOf(choice(s).place)));
  const settledFolders = new Set(byCount.filter((s) => choice(s).side === "ignores" && choice(s).place !== AUTOMATED && !fresh(s)).map((s) => keyOf(choice(s).place)));
  const ownNow = keptFolders.size;
  const biggest = (n: number) => {
    const labels = new Map<string, number>();
    for (const s of byCount) if (fresh(s)) labels.set(s.label, (labels.get(s.label) ?? 0) + s.count);
    const top = new Set([...labels.entries()].sort((a, b) => b[1] - a[1]).slice(0, Math.max(0, n - settledFolders.size)).map(([label]) => label));
    setChoices((current) => ({ ...current, ...Object.fromEntries(byCount.filter(fresh).map((s) => [s.sender, { side: "ignores", place: top.has(s.label) ? s.label : AUTOMATED }])) }));
  };
  // A whole folder to the other home: one that exists moves as itself; one only on this page
  // goes with its name. The "No folder" cards swap.
  const flip = (card: Card) => {
    const side = card.side === "reads" ? "ignores" : "reads";
    if (noFolder(card.place)) { move(card.members, across(card.side)); return; }
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
  const other = (card: Card) => (!noFolder(card.place) ? found.get(cardKey(card.side === "reads" ? "ignores" : "reads", card.place))?.members.length ?? 0 : 0);
  // A kept folder only this page has made is named here, before it exists.
  const naming = (card: Card) => card.side === "ignores" && !noFolder(card.place) && !card.real && !real("ignores", card.place) && !flipped[keyOf(card.place)] && card.members.length > 0;
  const show = (card: Card) => <FolderCard key={naming(card) ? card.members[0]?.sender ?? card.key : card.key} card={card} also={other(card)} onRename={naming(card) ? (name) => rename(card, name) : undefined} />;
  const choiceOf = (s: SortSender) => choice(s);

  return <div className="flex min-h-full flex-1 flex-col">
    <div className="flex flex-1 flex-col gap-5 px-5 py-6 md:px-6">
      {again ? <SplitReview /> : null}
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-2">
          <h1 className="font-serif text-title text-ink-primary">{t("mail.sort.title")}</h1>
          <p className="flex items-center gap-1 text-sm tabular-nums text-ink-muted">
            {owner ? `${owner} · ` : ""}{t("mail.sort.summary", { emails: fmt(total), kept: fmt(kept), read: fmt(total - kept) })}
            <Popover label={t("mail.sort.how")} trigger={<IconButton icon="info" label={t("mail.sort.how")} />}>
              <ul className="flex max-w-reading flex-col gap-2 text-sm text-ink-secondary">
                <li>{t("mail.sort.how.score")}</li>
                <li>{t("mail.sort.how.threshold")}</li>
                <li>{t("mail.sort.how.through")}</li>
              </ul>
            </Popover>
          </p>
          {alreadySorted > 0 ? <p className="text-sm tabular-nums text-ink-muted">{t("mail.sort.alreadySorted", { count: fmt(alreadySorted) })}</p> : null}
        </div>
        <span className="flex items-center gap-2 text-sm text-ink-secondary">
          {t("mail.sort.biggest.lead")}
          <span className="w-thumb"><Select compact label={t("mail.sort.biggest.label")} value={String(ownNow)} options={[...new Set([...BIGGEST, ownNow])].sort((a, b) => a - b).map((n) => ({ value: String(n), label: String(n) }))} onChange={(value) => biggest(Number(value))} /></span>
          {t("mail.sort.biggest.tail")}
        </span>
      </header>
      <Flash.Provider value={flash}>
      <Cards.Provider value={{ all: cards, move, flip }}>
      <Choosing.Provider value={choiceOf}>
      <div className="grid items-start gap-5 lg:grid-cols-2">
        <Column title={t("mail.sort.reads")} reads count={counted(reads)}>
          {movedNote("reads")}
          {suggested.length ? <Suggested items={suggested} declined={declined} onChange={(name, on) => setDeclined((current) => { const next = new Set(current); if (on) next.delete(name); else next.add(name); return next; })} /> : null}
          <FoldedCards cards={folders("reads")} render={show} />
          {show(inbox)}
          <NewFolder side="reads" onMake={(place) => setMade((list) => [...list, { side: "reads", place }])} />
        </Column>
        <Column title={t("mail.sort.ignores")} count={counted(ignores)}>
          {movedNote("ignores")}
          <FoldedCards cards={folders("ignores")} render={show} />
          {show(automated)}
          <NewFolder side="ignores" onMake={(place) => setMade((list) => [...list, { side: "ignores", place }])} />
          {calendar ? <p className="text-sm text-ink-muted">{t("mail.sort.calendar", { count: fmt(calendar) })}</p> : null}
        </Column>
      </div>
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
    <header className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="flex items-center gap-2 text-lg font-medium text-ink-primary"><span aria-hidden className={`h-2 w-2 rounded-full ${reads ? "bg-accent-default" : "bg-ink-faint"}`} />{title}</h2>
      <span className="text-sm tabular-nums text-ink-muted">{count}</span>
    </header>
    {children}
  </section>;
}

/** The biggest few folders, the rest a click away, so both sides open short. */
function FoldedCards({ cards, render }: { cards: readonly Card[]; render: (card: Card) => ReactNode }) {
  const [all, setAll] = useState(false);
  if (!cards.length) return null;
  const hidden = cards.slice(CARDS_SHOWN);
  return <>
    {(all ? cards : cards.slice(0, CARDS_SHOWN)).map(render)}
    {hidden.length ? <Button variant="quiet" className="self-start" onClick={() => setAll(!all)}>{all ? t("mail.sort.fewer") : t("mail.sort.moreGroups", { count: fmt(hidden.length), emails: fmt(hidden.reduce((n, card) => n + sizeOf(card.members), 0)) })}</Button> : null}
  </>;
}

/** One folder: its name and size, a switch that moves it all across, and its senders when
 *  opened. Senders can be dropped on it from any other card. */
function FolderCard({ card, also, onRename }: { card: Card; also: number; onRename?: ((name: string) => void) | undefined }) {
  const { all, move, flip } = useContext(Cards);
  const flashing = useContext(Flash);
  const [open, setOpen] = useState(false);
  const [over, setOver] = useState(false);
  const landed = card.members.some((s) => flashing.has(s.sender));
  const shown = open || landed;
  const catchAll = noFolder(card.place);
  const name = cardName(card.place);
  const to: Choice = { side: card.side, place: card.place };
  const summary = `${tn("mail.sort.senderCount", card.members.length)} · ${fmt(sizeOf(card.members))}`;
  return <div
    data-testid="sort-folder"
    data-side={card.side}
    data-folder={card.place}
    data-sort-key={card.members[0]?.sender}
    onDragOver={(event) => { if (event.dataTransfer.types.includes(DRAG)) { event.preventDefault(); setOver(true); } }}
    onDragLeave={() => setOver(false)}
    onDrop={(event) => { setOver(false); const sender = all.flatMap((c) => c.members).find((s) => s.sender === event.dataTransfer.getData(DRAG)); if (sender) move([sender], to); }}
    className={`flex flex-col gap-2 rounded-lg border bg-surface-raised p-3 transition-shadow duration-normal ${catchAll ? "border-dashed border-line-strong" : "border-line-subtle"} ${over ? "ring-2 ring-accent-default" : ""} ${flashClass(landed && !open)}`}>
    <div data-testid="sort-folder-head" className="flex items-center gap-3">
      <Pressable aria-expanded={shown} aria-label={t("mail.sort.open", { name })} onClick={() => setOpen(!open)} className="flex min-w-0 flex-1 items-center gap-2 rounded-md text-left">
        <Icon name={shown ? "chevronDown" : "chevronRight"} className="h-4 w-4 shrink-0 text-ink-muted" />
        <Icon name={card.place === "" ? "inbox" : card.side === "reads" ? "folder" : "keptFromAi"} className={`h-4 w-4 shrink-0 ${card.side === "reads" ? "text-accent-default" : "text-ink-muted"}`} />
        {onRename ? null : <span className="min-w-0 truncate text-md font-medium text-ink-primary">{name}</span>}
      </Pressable>
      {onRename ? <Input aria-label={t("mail.sort.categoryName")} value={card.place} maxLength={60} onChange={(event) => onRename(event.target.value)} className="min-w-0 flex-1" /> : null}
      <span className="shrink-0 text-sm tabular-nums text-ink-muted">{summary}</span>
      {card.members.length ? <SideSwitch side={card.side} name={name} onChange={(side) => side !== card.side && flip(card)} /> : null}
    </div>
    {card.place === AUTOMATED ? <p className="text-sm text-ink-muted">{t("mail.sort.automated.sub")}</p> : card.place === "" ? <p className="text-sm text-ink-muted">{t("mail.sort.noFolder.reads")}</p> : null}
    {onRename ? <p className="text-sm text-ink-muted">{t("mail.sort.path", { senders: tn("mail.sort.senderCount", card.members.length) })}</p> : null}
    {/* The count only when it isn't every sender, which the header already says. */}
    {card.real && card.members.some((s) => s.folder) ? <p className="text-sm text-ink-muted">{card.members.every((s) => s.folder) ? t("mail.sort.filed.all") : t("mail.sort.filed", { senders: tn("mail.sort.senderCount", card.members.filter((s) => s.folder).length) })}</p> : null}
    {also ? <p className="text-sm text-ink-muted">{t("mail.sort.also", { senders: tn("mail.sort.senderCount", also), side: t(card.side === "reads" ? "mail.sort.ignores" : "mail.sort.reads") })}</p> : null}
    {/* Empty, it says how to fill it, folded or not. */}
    {!card.members.length ? <p className="rounded-md border border-dashed border-line-subtle p-3 text-sm text-ink-muted">{t("mail.sort.empty")}</p> : shown ? <Folded items={card.members} /> : null}
  </div>;
}

function Folded({ items }: { items: readonly SortSender[] }) {
  const [all, setAll] = useState(false);
  const hidden = items.slice(SHOWN);
  return <div className="flex flex-col">
    <ul className="flex flex-col">{(all ? items : items.slice(0, SHOWN)).map((s) => <SenderRow key={s.sender} sender={s} />)}</ul>
    {hidden.length ? <Button variant="quiet" className="self-start" onClick={() => setAll(!all)}>{all ? t("mail.sort.fewer") : t("mail.sort.more", { count: fmt(hidden.length), emails: fmt(sizeOf(hidden)) })}</Button> : null}
  </div>;
}

/** Which side, said in words and changed in one press, so it never reads as a menu. */
function SideSwitch({ side, name, onChange }: { side: Choice["side"]; name: string; onChange: (side: Choice["side"]) => void }) {
  return <Segmented label={t("mail.sort.side", { name })} hideLabel value={side} options={[{ value: "reads", label: t("mail.sort.side.reads") }, { value: "ignores", label: t("mail.sort.side.ignores") }]} onChange={onChange} />;
}

function why(s: SortSender): string {
  const parts: string[] = [];
  if (s.repeats >= 0.5) parts.push(t("mail.sort.why.repeats", { pct: Math.round(s.repeats * 100) }));
  if (s.bulk >= 0.5) parts.push(t("mail.sort.why.bulk"));
  if (s.one_way) parts.push(t("mail.sort.why.oneWay"));
  return parts.join(" · ");
}

/** One sender, short: who, how many, how automated, which side. Its details and emails open on
 *  a press, with a folder picker that does what dragging it does. */
function SenderRow({ sender: s }: { sender: SortSender }) {
  const { all, move } = useContext(Cards);
  const now = useContext(Choosing)(s);
  const flashing = useContext(Flash);
  const [open, setOpen] = useState(false);
  const ignored = now.side === "ignores";
  const pct = Math.round(s.score * 100);
  const reasons = [why(s), s.kept ? t("mail.sort.kept", { why: s.kept.toLocaleLowerCase() }) : "", ignored && s.reach ? t("mail.sort.reach", { count: fmt(s.reach) }) : ""].filter(Boolean);
  const here = cardKey(now.side, now.place);
  return <li draggable onDragStart={(event) => { event.dataTransfer.setData(DRAG, s.sender); event.dataTransfer.effectAllowed = "move"; }} data-testid="sort-sender" data-side={now.side} data-sort-key={s.sender} className={`flex flex-col gap-2 rounded-md border-t border-line-subtle py-2 first:border-t-0 ${flashClass(flashing.has(s.sender))}`}>
    <div className="flex items-center gap-3">
      <Icon name="grip" className="h-4 w-4 shrink-0 cursor-grab text-ink-faint" />
      <Pressable aria-expanded={open} onClick={() => setOpen(!open)} className="flex min-w-0 flex-1 flex-col rounded-md text-left">
        <span className="truncate text-md text-ink-primary">{s.label}</span>
        <span className="truncate text-sm text-ink-muted">{s.sender}</span>
      </Pressable>
      <span className="shrink-0 text-md tabular-nums text-ink-secondary">{fmt(s.count)}</span>
      <span className="hidden w-thumb shrink-0 md:block"><Progress label={t("mail.sort.score", { pct })} value={pct} /></span>
      <SideSwitch side={now.side} name={s.label} onChange={(side) => side !== now.side && move([s], across(now.side))} />
    </div>
    {open ? <div className="flex flex-col gap-2 pl-7">
      <p className="text-sm tabular-nums text-ink-secondary">{[t("mail.sort.score", { pct }), ...reasons].join(" · ")}</p>
      <span className="max-w-reading"><Select compact label={t("mail.sort.moveTo", { name: s.label })} value={here} options={all.map((c) => ({ value: c.key, label: `${t(c.side === "reads" ? "mail.sort.reads" : "mail.sort.ignores")} · ${cardName(c.place)}` }))} onChange={(key) => { const card = all.find((c) => c.key === key); if (card && key !== here) move([s], { side: card.side, place: card.place }); }} /></span>
      <ul className="flex flex-col gap-1 border-l border-line-subtle pl-3">
        {s.emails.map((email, index) => <li key={`${email.subject}-${index}`} className="flex items-baseline justify-between gap-3 text-sm">
          <span className="min-w-0 truncate text-ink-primary">{email.subject || t("mail.sort.noSubject")}</span>
          <span className="flex shrink-0 items-center gap-2">
            {ignored && email.names_you ? <Badge tone="accent">{t("mail.sort.through")}</Badge> : null}
            <span className="tabular-nums text-ink-muted">{email.when}</span>
          </span>
        </li>)}
      </ul>
    </div> : null}
  </li>;
}

/** A folder made here, on one side, at the top of that home. */
function NewFolder({ side, onMake }: { side: Choice["side"]; onMake: (place: string) => void }) {
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const make = () => {
    const clean = name.trim().replaceAll("/", " ").slice(0, 50);
    if (clean) onMake(clean);
    setName("");
    setNaming(false);
  };
  if (!naming) return <Button variant="quiet" className="self-start border border-dashed border-line-strong" onClick={() => setNaming(true)}>{t(side === "reads" ? "mail.sort.new.reads" : "mail.sort.new.ignores")}</Button>;
  return <form className="flex items-center gap-2" onSubmit={(event) => { event.preventDefault(); make(); }}>
    <Input autoFocus aria-label={t("mail.sort.new.name")} value={name} maxLength={50} onChange={(event) => setName(event.target.value)} className="min-w-0 flex-1" />
    <Button type="submit" variant="primary" disabled={!name.trim()}>{t("mail.sort.new.add")}</Button>
    <Button variant="quiet" onClick={() => setNaming(false)}>{t("mail.sort.new.cancel")}</Button>
  </form>;
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
