"use client";

import Link from "next/link";
import appConfig from "@/app.config.json";
import { useEffect, useState, type ReactNode } from "react";
import type { MatterRow } from "@/ui/client/contracts.generated";
import { useAgentName, useMattersBrief } from "@/ui/client/work";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { fullHref, mailSource } from "@/ui/features/sources/kinds";
import { Icon, type IconName } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { Pressable } from "@/ui/primitives/Pressable";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";
import { useMatterActions } from "./matterActions";
import { SourceLink, countsOf, useDue, useTodayView } from "./parts";

// How long a conversation can sit quietly before it's worth a nudge.
const QUIET_DAYS = 3;
// The first screen shows a few, not twenty: the rest are a click away and nothing is lost.
const FIRST_SHOWN = 5;

/** The matters with a change the person hasn't seen yet: the Since you last looked line counts
 *  them, and each card marks itself. */
export function useChangedMatters(): Set<number> {
  const brief = useMattersBrief();
  const seen = brief.data?.seen ? Date.parse(brief.data.seen) : null;
  // As times, not text: an email's own date can carry its sender's offset.
  return new Set((brief.data?.changes ?? []).filter((change) => seen === null || Date.parse(change.time) > seen).map((change) => change.matter));
}

function MatterCard({ matter, chase = false, changed = false, suggested = false }: { matter: MatterRow; chase?: boolean; changed?: boolean; suggested?: boolean }) {
  const due = useDue();
  const actions = useMatterActions(matter);
  const { go } = useTodayView();
  const when = matter.due ? due(matter.due) : null;
  const thread = matter.latest ? Number(matter.latest.ref) : null;
  const idea = suggested ? (matter.work ?? []).find((item) => item.proposed) : undefined;
  return (
    <ContextMenu items={actions}>
    <Rise as="li" settle data-testid={suggested ? "matter-suggested" : "matter-row"} className={suggested ? "my-2 flex flex-col gap-2 rounded-md border border-dashed border-line-strong bg-surface-sunken/40 p-3" : "flex flex-col gap-2 border-t border-line-subtle py-3 first:border-t-0"}>
      {suggested ? <span className="text-sm text-ink-muted">{t("matters.onlySuggested")}</span> : null}
      <div className="flex items-baseline justify-between gap-3">
        {/* The matter is the thing here: its title is the way into it. */}
        <Pressable onClick={() => go("matters", matter.id)} aria-label={t("matters.open", { title: matter.title })} className="group flex min-w-0 items-center gap-2 rounded-sm text-left text-lg font-medium text-ink-primary transition-colors duration-fast hover:text-accent-default">
          {matter.importance === "high" ? <span aria-label={t("today.important")} role="img" className="h-2 w-2 shrink-0 rounded-full bg-accent-default" /> : null}
          <span className="min-w-0 truncate">{matter.title}</span>
          <Icon name="chevronRight" className="h-3 w-3 shrink-0 text-ink-faint transition-colors duration-fast group-hover:text-accent-default" />
        </Pressable>
        {when ? <span className={`shrink-0 text-sm tabular-nums ${when.overdue ? "font-medium text-status-danger" : "text-status-warning"}`}>{when.text}</span> : null}
      </div>
      <p className="text-sm text-ink-muted">
        {[(matter.people ?? []).slice(0, 3).join(", "), countsOf(matter)].filter(Boolean).join(" · ")}
        {changed ? <span data-testid="matter-changed" className="font-medium text-accent-default"> · {t("matters.changed")}</span> : null}
      </p>
      {idea ? <p className="text-md text-ink-secondary">{t("matters.suggestedNext", { next: idea.title })}</p> : matter.next ? <p className="text-md text-ink-secondary">{t("matters.next", { next: matter.next })}</p> : null}
      {matter.latest ? (
        <p className="flex min-w-0 items-center gap-2 text-sm text-ink-muted">
          <Icon name="fromEmail" className="h-3 w-3 shrink-0" />
          <SourceLink source={matter.latest} testid="today-thread"><span className="truncate">{matter.latest.title}</span></SourceLink>
        </p>
      ) : null}
      {!suggested ? (
        <span className="flex flex-wrap items-center gap-2 empty:hidden">
          {chase && thread ? <AskAgent context={[`mail:${thread}`]} title={t("today.chase.title")} label={t("today.chase.draft")} text={t("today.chase.ask")} /> : null}
          {!chase && thread && matter.state === "waiting_on_you" ? <Link href={`${fullHref(mailSource(thread))}?draft`} data-testid="today-draft" className="focus-ring press ai-glow relative inline-flex items-center rounded-md px-3 py-2 text-md font-medium text-ink-primary">{t("mail.draftReply")}</Link> : null}
        </span>
      ) : null}
    </Rise>
    </ContextMenu>
  );
}

function Group({ id, icon, title, urgent = false, matters, quiet = false, suggested = [], aside }: { id?: string; icon: IconName; title: string; urgent?: boolean; matters: readonly MatterRow[]; quiet?: boolean; suggested?: readonly MatterRow[]; aside?: ReactNode }) {
  const [all, setAll] = useState(false);
  const changed = useChangedMatters();
  if (!matters.length && !suggested.length && !aside) return null;
  const shown = all ? matters : matters.slice(0, FIRST_SHOWN);
  return (
    <section id={id} aria-label={title} className={`flex scroll-mt-4 flex-col gap-1 rounded-lg border bg-surface-raised p-4 shadow-raised ${urgent ? "border-accent-default" : "border-line-subtle"}`}>
      <header className="flex flex-wrap items-center gap-3 pb-1">
        <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${urgent ? "bg-accent-default text-accent-on" : "bg-surface-sunken text-ink-secondary"}`}><Icon name={icon} /></span>
        <h2 className="flex flex-1 items-center gap-2 text-lg font-medium text-ink-primary">{title}<span className="text-md tabular-nums text-ink-muted">{matters.length}</span></h2>
        {aside}
      </header>
      <ul className="flex flex-col">
        <Presence>
          {shown.map((matter) => <MatterCard key={matter.id} matter={matter} changed={changed.has(matter.id)} chase={quiet && (matter.quiet_days ?? 0) >= QUIET_DAYS} />)}
          {suggested.map((matter) => <MatterCard key={`s-${matter.id}`} matter={matter} changed={changed.has(matter.id)} suggested />)}
        </Presence>
      </ul>
      {matters.length > FIRST_SHOWN ? <Button variant="quiet" className="self-start" onClick={() => setAll(!all)}>{all ? t("today.showFewer") : t("today.showMore", { count: matters.length - FIRST_SHOWN })}</Button> : null}
    </section>
  );
}

/** Whether Posty's suggestions join Waiting on you. Remembered on this computer, like the rest
 *  of how Today looks here. */
function useIncludeSuggested(): [boolean, (next: boolean) => void] {
  const [on, setOn] = useState(false);
  useEffect(() => {
    try {
      setOn(localStorage.getItem(appConfig.storageKeys.includeSuggested) === "true");
    } catch {
      // Storage can be blocked; the switch then starts off.
    }
  }, []);
  const change = (next: boolean) => {
    setOn(next);
    try {
      localStorage.setItem(appConfig.storageKeys.includeSuggested, String(next));
    } catch {
      // Storage can be blocked; the choice then lasts until reload.
    }
  };
  return [on, change];
}

/** What's going on, by who moves next. Each matter once, with its work and its latest email.
 *  Waiting on you is only what's theirs; Posty's suggestions join it when they ask. */
export function MatterGroups() {
  const brief = useMattersBrief();
  const agent = useAgentName()("mail");
  const [withSuggested, setWithSuggested] = useIncludeSuggested();
  const data = brief.data;
  if (!data) return brief.isPending ? <Skeleton className="h-6 w-full" /> : null;
  const suggested = data.suggested ?? [];
  // Shown with Waiting on you, a matter leaves the group it was in: each matter once.
  const moved = new Set(withSuggested ? suggested.map((matter) => matter.id) : []);
  const rest = (matters: readonly MatterRow[]) => matters.filter((matter) => !moved.has(matter.id));
  // Empty, the page's one "All clear" line says it.
  if (!data.needs_you.length && !data.waiting.length && !data.fyi.length && !suggested.length) return null;
  const toggle = suggested.length ? <span data-testid="include-suggested"><Checkbox label={t("matters.includeSuggested", { agent, count: suggested.length })} checked={withSuggested} onChange={setWithSuggested} /></span> : undefined;
  return (
    <>
      <Group id="today-important" icon="priority" title={t("matters.group.needsYou")} urgent matters={data.needs_you} suggested={withSuggested ? suggested : []} {...(toggle ? { aside: toggle } : {})} />
      <Group id="today-waiting" icon="sent" title={t("matters.group.waiting")} matters={rest(data.waiting)} quiet />
      <Group icon="info" title={t("matters.group.fyi")} matters={rest(data.fyi)} />
    </>
  );
}
