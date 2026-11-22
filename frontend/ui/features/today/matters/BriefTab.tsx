"use client";

import Link from "next/link";
import { useState } from "react";
import type { MatterChange, MatterRow } from "@/ui/client/contracts.generated";
import { useShortDate, useTimeOnly } from "@/ui/client/format";
import { useMattersBrief } from "@/ui/client/work";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { fullHref, mailSource } from "@/ui/features/sources/kinds";
import { Icon, type IconName } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { Pressable } from "@/ui/primitives/Pressable";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { MarkGlyph } from "@/ui/primitives/Track";
import { t } from "@/ui/strings";
import { KIND_MARK, SourceLink, countsOf, kindLabel, useDue, useMatterDoneWithUndo, useTodayView } from "./parts";

// How long a conversation can sit quietly before it's worth a nudge.
const QUIET_DAYS = 3;
// The first screen shows a few, not twenty: the rest are a click away and nothing is lost.
const FIRST_SHOWN = 5;

/** The brief between mornings: one line for each change to a matter, newest first. */
export function RunningBrief() {
  const brief = useMattersBrief();
  const time = useTimeOnly();
  const day = useShortDate();
  const { go } = useTodayView();
  if (brief.isError) return <ErrorState title={t("matters.error")} onRetry={() => void brief.refetch()} />;
  const changes = brief.data?.changes ?? [];
  const seen = brief.data?.seen;
  // Empty, it would only push what does need doing down the page.
  if (brief.isSuccess && changes.length === 0) return null;
  const unseen = (change: MatterChange) => !seen || change.time > seen;
  return (
    <section aria-label={t("matters.running")} data-testid="running-brief" className="flex flex-col gap-3 rounded-lg border border-line-subtle bg-surface-raised p-4 shadow-raised">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-medium text-ink-primary">{t("matters.since")}</h2>
        {seen ? <p className="text-sm tabular-nums text-ink-muted">{t("matters.since.seen", { when: day(seen) })}</p> : null}
      </header>
      {brief.isPending ? <Skeleton className="h-6 w-full" /> : null}
      <ol className="flex flex-col">
        <Presence>
          {changes.map((change) => (
            <Rise as="li" settle key={change.id} data-testid="matter-change" className="grid grid-cols-change gap-3 border-t border-line-subtle py-3 first:border-t-0 first:pt-0">
              <span className={`flex items-start gap-1 pt-px text-sm tabular-nums ${unseen(change) ? "font-medium text-accent-default" : "text-ink-muted"}`}>
                {time(change.time)}
                {unseen(change) ? <span role="img" aria-label={t("matters.unseen")} className="mt-1 h-2 w-2 shrink-0 rounded-full bg-accent-default" /> : null}
              </span>
              <span className="flex pt-1"><MarkGlyph {...KIND_MARK[change.kind]} /></span>
              <ChangeLine change={change} onOpen={() => go("matters", change.matter)} />
            </Rise>
          ))}
        </Presence>
      </ol>
    </section>
  );
}

function ChangeLine({ change, onOpen }: { change: MatterChange; onOpen: () => void }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <p className="text-md text-ink-primary">
        <Pressable onClick={onOpen} className="rounded-sm text-left font-medium transition-colors duration-fast hover:text-accent-default">{change.title}</Pressable>
        <span className="text-ink-muted"> · {kindLabel(change.kind)}</span>
      </p>
      {change.text !== change.title ? <p className="text-md text-ink-secondary">{change.text}</p> : null}
      {change.why ? <p className="text-sm text-ink-muted">{t("matters.why", { why: change.why })}</p> : null}
      {change.source ? <p className="truncate text-sm"><SourceLink source={change.source}>{change.source.detail ? `${change.source.detail} · ` : ""}{change.source.title}</SourceLink></p> : null}
    </div>
  );
}

function MatterCard({ matter, chase = false }: { matter: MatterRow; chase?: boolean }) {
  const due = useDue();
  const finish = useMatterDoneWithUndo();
  const { go } = useTodayView();
  const when = matter.due ? due(matter.due) : null;
  const thread = matter.latest ? Number(matter.latest.ref) : null;
  return (
    <Rise as="li" settle data-testid="matter-row" className="flex flex-col gap-2 border-t border-line-subtle py-3 first:border-t-0">
      <div className="flex items-baseline justify-between gap-3">
        <span className="flex min-w-0 items-center gap-2">
          {matter.importance === "high" ? <span aria-label={t("today.important")} role="img" className="h-2 w-2 shrink-0 rounded-full bg-accent-default" /> : null}
          <Pressable onClick={() => go("matters", matter.id)} aria-label={t("matters.open", { title: matter.title })} className="min-w-0 truncate rounded-sm text-left text-md font-medium text-ink-primary transition-colors duration-fast hover:text-accent-default">{matter.title}</Pressable>
        </span>
        {when ? <span className={`shrink-0 text-sm tabular-nums ${when.overdue ? "font-medium text-status-danger" : "text-status-warning"}`}>{when.text}</span> : null}
      </div>
      <p className="truncate text-sm text-ink-muted">{[(matter.people ?? []).slice(0, 3).join(", "), countsOf(matter)].filter(Boolean).join(" · ")}</p>
      {matter.next ? <p className="text-sm text-ink-secondary">{t("matters.next", { next: matter.next })}</p> : null}
      {matter.latest ? (
        <p className="flex min-w-0 items-center gap-2 text-sm">
          <Icon name="fromEmail" className="h-4 w-4 shrink-0 text-ink-muted" />
          <SourceLink source={matter.latest} testid="today-thread"><span className="truncate">{matter.latest.title}</span></SourceLink>
        </p>
      ) : null}
      <span className="flex flex-wrap items-center gap-2">
        {chase && thread ? <AskAgent context={[`mail:${thread}`]} title={t("today.chase.title")} label={t("today.chase.draft")} text={t("today.chase.ask")} /> : null}
        {!chase && thread && matter.state === "waiting_on_you" ? <Link href={`${fullHref(mailSource(thread))}?draft`} data-testid="today-draft" className="focus-ring press ai-glow relative inline-flex items-center rounded-md px-3 py-2 text-md font-medium text-ink-primary">{t("mail.draftReply")}</Link> : null}
        <Button variant="quiet" data-testid="matter-done" onClick={() => finish(matter)}>{t("matters.done")}</Button>
      </span>
    </Rise>
  );
}

function Group({ id, icon, title, urgent = false, matters, quiet = false }: { id?: string; icon: IconName; title: string; urgent?: boolean; matters: readonly MatterRow[]; quiet?: boolean }) {
  const [all, setAll] = useState(false);
  if (!matters.length) return null;
  const shown = all ? matters : matters.slice(0, FIRST_SHOWN);
  return (
    <section id={id} aria-label={title} className={`flex scroll-mt-4 flex-col gap-1 rounded-lg border bg-surface-raised p-4 shadow-raised ${urgent ? "border-accent-default" : "border-line-subtle"}`}>
      <header className="flex items-center gap-3 pb-1">
        <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${urgent ? "bg-accent-default text-accent-on" : "bg-surface-sunken text-ink-secondary"}`}><Icon name={icon} /></span>
        <h2 className="flex items-center gap-2 text-lg font-medium text-ink-primary">{title}<span className="text-md tabular-nums text-ink-muted">{matters.length}</span></h2>
      </header>
      <ul className="flex flex-col">
        <Presence>{shown.map((matter) => <MatterCard key={matter.id} matter={matter} chase={quiet && (matter.quiet_days ?? 0) >= QUIET_DAYS} />)}</Presence>
      </ul>
      {matters.length > FIRST_SHOWN ? <Button variant="quiet" className="self-start" onClick={() => setAll(!all)}>{all ? t("today.showFewer") : t("today.showMore", { count: matters.length - FIRST_SHOWN })}</Button> : null}
    </section>
  );
}

/** What's going on, by who moves next. Each matter once, with its work and its latest email. */
export function MatterGroups() {
  const brief = useMattersBrief();
  const data = brief.data;
  if (!data) return brief.isPending ? <Skeleton className="h-6 w-full" /> : null;
  // Empty, the page's one "All clear" line says it.
  if (!data.needs_you.length && !data.waiting.length && !data.fyi.length) return null;
  return (
    <>
      <Group id="today-important" icon="priority" title={t("matters.group.needsYou")} urgent matters={data.needs_you} />
      <Group id="today-waiting" icon="sent" title={t("matters.group.waiting")} matters={data.waiting} quiet />
      <Group icon="info" title={t("matters.group.fyi")} matters={data.fyi} />
    </>
  );
}
