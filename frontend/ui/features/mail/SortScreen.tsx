"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { command, query } from "@/ui/client/api";
import type { SortSender } from "@/ui/client/contracts.generated";
import { useHomeReady, useLeadName } from "@/ui/client/home";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Progress } from "@/ui/primitives/Progress";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t, tn } from "@/ui/strings";

/** Where each sender stands: the side, and on the ignored side its own category and name. */
interface Choice {
  side: SortSender["side"];
  own: boolean;
  name: string;
}
type Choices = Record<string, Choice>;

// Lists show this many until opened, so the biggest senders are what shows.
const SHOWN = 8;
const fmt = (n: number) => n.toLocaleString();
const keyOf = (name: string) => name.trim().toLocaleLowerCase();

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
  const prepare = useMutation({ mutationFn: () => command("mail.sort.prepare", {}), onSuccess: (data) => client.setQueryData(["mail-sort"], data) });
  const refresh = () => Promise.all(["mail-sort", "categories", "threads", "today"].map((key) => client.invalidateQueries({ queryKey: [key] })));
  const state = sort.data?.state;
  // Asked once when the page opens too, so mail that came in after scoring gets scored.
  const asked = useRef(false);
  useEffect(() => {
    if (!state || prepare.isPending) return;
    if (state === "none" || (state === "ready" && !asked.current)) {
      asked.current = true;
      prepare.mutate();
    }
  }, [state]);

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
  return <Sorter senders={sort.data.senders ?? []} owner={sort.data.owner_name ?? ""} total={sort.data.emails ?? 0} calendar={sort.data.calendar ?? 0} alreadySorted={sort.data.already_sorted ?? 0} lead={lead} onDone={finished} back={back} />;
}

function Sorter({ senders, owner, total, calendar, alreadySorted, lead, onDone, back }: { senders: readonly SortSender[]; owner: string; total: number; calendar: number; alreadySorted: number; lead: string; onDone: () => void; back: ReactNode }) {
  const byCount = [...senders].sort((a, b) => b.count - a.count);
  const [choices, setChoices] = useState<Choices>(() => {
    const start: Choices = Object.fromEntries(byCount.map((s) => [s.sender, { side: s.side, own: s.own, name: s.label }]));
    // A sender named like a category that starts on its own joins it, so one tool is one category.
    const named = new Set(byCount.filter((s) => s.own).map((s) => keyOf(s.label)));
    for (const s of byCount) if (s.side === "ignores" && named.has(keyOf(s.label))) (start[s.sender] as Choice).own = true;
    return start;
  });
  const change = (sender: string, patch: Partial<Choice>) => setChoices((current) => ({ ...current, [sender]: { ...(current[sender] as Choice), ...patch } }));
  const choice = (s: SortSender) => choices[s.sender] as Choice;
  const apply = useMutation({
    mutationFn: () => command("mail.sort.apply", { senders: byCount.map((s) => ({ sender: s.sender, side: choice(s).side, own: choice(s).own, name: choice(s).name === s.label ? "" : choice(s).name.slice(0, 60) })) }),
    onSuccess: onDone,
  });
  const skip = useMutation({ mutationFn: () => command("mail.sort.skip", {}), onSuccess: onDone });

  const reads = byCount.filter((s) => choice(s).side === "reads");
  const ignores = byCount.filter((s) => choice(s).side === "ignores");
  const categories = groupByName(ignores.filter((s) => choice(s).own), choices);
  const rest = ignores.filter((s) => !choice(s).own);
  const kept = ignores.reduce((n, s) => n + s.count - s.reach, 0) + calendar;
  const counted = (list: readonly SortSender[]) => `${tn("mail.sort.senderCount", list.length)} · ${tn("mail.sort.emailCount", list.reduce((n, s) => n + s.count, 0))}`;
  const row = (s: SortSender, inCard = false) => <SenderRow key={s.sender} sender={s} choice={choice(s)} inCard={inCard} onChange={(patch) => change(s.sender, patch)} />;

  return <div className="flex min-h-full flex-1 flex-col">
    <div className="flex flex-1 flex-col gap-5 px-5 py-6 md:px-6">
      <header className="flex flex-col gap-2">
        <h1 className="font-serif text-title text-ink-primary">{t("mail.sort.title")}</h1>
        <p className="text-sm tabular-nums text-ink-muted">{owner ? `${owner} · ` : ""}{t("mail.sort.summary", { emails: fmt(total), kept: fmt(kept), read: fmt(total - kept) })}</p>
        {alreadySorted > 0 ? <p className="text-sm tabular-nums text-ink-muted">{t("mail.sort.alreadySorted", { count: fmt(alreadySorted) })}</p> : null}
        <ul className="flex max-w-reading flex-col gap-1 text-sm text-ink-secondary">
          <li>{t("mail.sort.how.score")}</li>
          <li>{t("mail.sort.how.threshold")}</li>
          <li>{t("mail.sort.how.through")}</li>
        </ul>
      </header>
      <div className="grid items-start gap-5 lg:grid-cols-2">
        <Column title={t("mail.sort.reads")} folder={t("mail.sort.folder.inbox")} reads count={counted(reads)}>
          <Folded items={reads} render={(s) => row(s)} />
        </Column>
        <Column title={t("mail.sort.ignores")} folder={t("mail.sort.folder.automated")} count={counted(ignores)}>
          {categories.length ? <p className="text-sm text-ink-muted">{t("mail.sort.own.sub")}</p> : null}
          {/* Keyed by its first sender, not its name, so typing a new name doesn't remount it. */}
          {categories.map((category) => {
            // Senders the AI reads that go by this name, or by the name a member started with.
            const names = new Set([category.key, ...category.members.map((s) => keyOf(s.label))]);
            const elsewhere = reads.filter((s) => names.has(keyOf(s.label)));
            const moveHere = () => { for (const s of elsewhere) change(s.sender, { side: "ignores", own: true, name: category.name }); };
            return <CategoryCard key={category.members[0]?.sender ?? category.key} name={category.name} members={category.members} elsewhere={elsewhere.length} onMoveHere={moveHere} onRename={(name) => { for (const s of category.members) change(s.sender, { name }); }}>
            {category.members.map((s) => row(s, true))}
          </CategoryCard>;
          })}
          {rest.length ? <p className="text-sm text-ink-muted">{t("mail.sort.rest.sub")}</p> : null}
          <Folded items={rest} render={(s) => row(s)} />
          {calendar ? <p className="text-sm text-ink-muted">{t("mail.sort.calendar", { count: fmt(calendar) })}</p> : null}
        </Column>
      </div>
    </div>
    <footer className="sticky bottom-0 flex flex-wrap items-center justify-between gap-3 border-t border-line-subtle bg-surface-raised px-5 py-3 md:px-6">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-sm text-ink-muted">{`${tn("mail.sort.foot.categories", categories.length)}, ${tn("mail.sort.foot.rest", rest.length)}. ${t("mail.sort.foot.rules")}`}</p>
        <p className="text-sm text-ink-muted">{t("mail.sort.finish.note", { name: lead })}</p>
        {apply.isError || skip.isError ? <p role="alert" className="text-sm text-status-danger">{(apply.error ?? skip.error)?.message}</p> : null}
      </div>
      <div className="flex items-center gap-2">
        {back}
        <Button variant="quiet" loading={skip.isPending} disabled={apply.isPending} onClick={() => skip.mutate()}>{t("mail.sort.skip")}</Button>
        <Button variant="primary" loading={apply.isPending} disabled={skip.isPending} onClick={() => apply.mutate()}>{t("mail.sort.finish")}</Button>
      </div>
    </footer>
  </div>;
}

/** Senders on the ignored side with the same category name are one category. */
function groupByName(owned: readonly SortSender[], choices: Choices): { key: string; name: string; members: SortSender[] }[] {
  const found = new Map<string, { key: string; name: string; members: SortSender[] }>();
  for (const s of owned) {
    // The box shows the name as typed, spaces and all; only matching ignores case and spaces.
    const name = choices[s.sender]?.name ?? s.label;
    const key = keyOf(name) || s.sender;
    if (!found.has(key)) found.set(key, { key, name, members: [] });
    found.get(key)?.members.push(s);
  }
  return [...found.values()];
}

function Column({ title, folder, reads = false, count, children }: { title: string; folder: string; reads?: boolean; count: string; children: ReactNode }) {
  return <section aria-label={title} className="flex min-w-0 flex-col gap-3 rounded-lg border border-line-subtle bg-surface-raised p-4 shadow-raised">
    <header className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="flex items-center gap-2 text-lg font-medium text-ink-primary">{title}<Badge tone={reads ? "success" : "neutral"}>{folder}</Badge></h2>
      <span className="text-sm tabular-nums text-ink-muted">{count}</span>
    </header>
    {children}
  </section>;
}

function Folded({ items, render }: { items: readonly SortSender[]; render: (sender: SortSender) => ReactNode }) {
  const [all, setAll] = useState(false);
  if (!items.length) return null;
  const shown = all ? items : items.slice(0, SHOWN);
  const hidden = items.slice(SHOWN);
  return <div className="flex flex-col">
    <ul className="flex flex-col">{shown.map(render)}</ul>
    {hidden.length ? <Button variant="quiet" className="self-start" onClick={() => setAll(!all)}>{all ? t("mail.sort.fewer") : t("mail.sort.more", { count: fmt(hidden.length), emails: fmt(hidden.reduce((n, s) => n + s.count, 0)) })}</Button> : null}
  </div>;
}

function CategoryCard({ name, members, elsewhere, onMoveHere, onRename, children }: { name: string; members: readonly SortSender[]; elsewhere: number; onMoveHere: () => void; onRename: (name: string) => void; children: ReactNode }) {
  const count = members.reduce((n, s) => n + s.count, 0);
  const senders = tn("mail.sort.senderCount", members.length);
  return <div data-testid="sort-category" className="flex flex-col gap-2 rounded-md border border-line-subtle bg-surface-page p-3">
    <div className="flex items-center gap-3">
      <Input aria-label={t("mail.sort.categoryName")} value={name} maxLength={60} onChange={(event) => onRename(event.target.value)} className="min-w-0 flex-1" />
      <span className="shrink-0 text-md tabular-nums text-ink-secondary">{fmt(count)}</span>
    </div>
    <p className="text-sm text-ink-muted">{t("mail.sort.path", { name: name.trim() || "…", senders })}</p>
    {elsewhere ? <Button variant="quiet" className="-ml-3 self-start py-px" onClick={onMoveHere}>{tn("mail.sort.moveHere", elsewhere)}</Button> : null}
    <ul className="flex flex-col">{children}</ul>
  </div>;
}

function why(s: SortSender): string {
  const parts: string[] = [];
  if (s.repeats >= 0.5) parts.push(t("mail.sort.why.repeats", { pct: Math.round(s.repeats * 100) }));
  if (s.bulk >= 0.5) parts.push(t("mail.sort.why.bulk"));
  if (s.one_way) parts.push(t("mail.sort.why.oneWay"));
  return parts.join(" · ");
}

/** One sender: its name, how many, how automated it looks and why, and a way across. */
function SenderRow({ sender: s, choice, inCard, onChange }: { sender: SortSender; choice: Choice; inCard: boolean; onChange: (patch: Partial<Choice>) => void }) {
  const [open, setOpen] = useState(false);
  const ignored = choice.side === "ignores";
  const pct = Math.round(s.score * 100);
  const reasons = [why(s), s.kept ? t("mail.sort.kept", { why: s.kept.toLocaleLowerCase() }) : "", ignored && s.reach ? t("mail.sort.reach", { count: fmt(s.reach) }) : ""].filter(Boolean);
  const move = <IconButton icon={ignored ? "chevronLeft" : "chevronRight"} label={t(ignored ? "mail.sort.toRead" : "mail.sort.toIgnore", { name: s.label })} onClick={() => onChange({ side: ignored ? "reads" : "ignores" })} />;
  return <li data-testid="sort-sender" data-side={choice.side} className="flex flex-col gap-2 border-t border-line-subtle py-3 first:border-t-0">
    <div className="flex items-start gap-3">
      {ignored && !inCard ? <div className="pt-1"><Checkbox label={t("mail.sort.ownToggle", { name: s.label })} hideLabel checked={choice.own} onChange={(own) => onChange({ own })} /></div> : null}
      {!ignored ? move : null}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-baseline justify-between gap-3">
          <span className="truncate text-md font-medium text-ink-primary">{inCard ? s.sender : s.label}</span>
          <span className="shrink-0 text-md tabular-nums text-ink-secondary">{fmt(s.count)}</span>
        </div>
        <p className="truncate text-sm text-ink-muted">{[inCard ? "" : s.sender, s.examples[0] ?? ""].filter(Boolean).join(" · ")}</p>
        <div className="flex items-center gap-3">
          <span className="w-thumb shrink-0"><Progress label={t("mail.sort.score", { pct })} value={pct} /></span>
          <span className="min-w-0 text-sm tabular-nums text-ink-secondary">{[t("mail.sort.score", { pct }), ...reasons].join(" · ")}</span>
        </div>
        <Button variant="quiet" className="-ml-3 self-start py-px" aria-expanded={open} onClick={() => setOpen(!open)}>{t(open ? "mail.sort.emails.hide" : "mail.sort.emails.show")}</Button>
        {open ? <ul className="flex flex-col gap-1 border-l border-line-subtle pl-3">
          {s.emails.map((email, index) => <li key={`${email.subject}-${index}`} className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate text-ink-primary">{email.subject || t("mail.sort.noSubject")}</span>
            <span className="flex shrink-0 items-center gap-2">
              {ignored && email.names_you ? <Badge tone="accent">{t("mail.sort.through")}</Badge> : null}
              <span className="tabular-nums text-ink-muted">{email.when}</span>
            </span>
          </li>)}
        </ul> : null}
      </div>
      {ignored ? move : null}
    </div>
  </li>;
}
