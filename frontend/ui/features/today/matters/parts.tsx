"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { MatterChange, MatterMark, MatterRow } from "@/ui/client/contracts.generated";

export type MatterState = MatterRow["state"];
export type MatterEventKind = MatterChange["kind"];
export type MatterMarkKind = MatterMark["kind"];
import { useDateOnly, useDateTime } from "@/ui/client/format";
import { useMatterDone, useMatterReopen } from "@/ui/client/work";
import { useOpenSource } from "@/ui/features/sources/context";
import { fullHref, type PreviewSource } from "@/ui/features/sources/kinds";
import { Badge } from "@/ui/primitives/Badge";
import { quickLook } from "@/ui/primitives/SourceRef";
import { useToast } from "@/ui/primitives/Toast";
import type { MarkShape, MarkTone } from "@/ui/primitives/Track";
import { t, tn, type StringKey } from "@/ui/strings";

export type TodayView = "brief" | "week" | "matters";
export const VIEWS: readonly TodayView[] = ["brief", "week", "matters"];

const STATE_TONE: Record<MatterState, "accent" | "neutral" | "warning" | "success"> = {
  waiting_on_you: "accent",
  waiting_on_others: "neutral",
  fyi: "warning",
  done: "success",
};

/** The state as quiet text, with a dot only when it's the person's move. */
export function StateText({ state }: { state: MatterState }) {
  return (
    <span className={`flex items-center gap-2 text-sm ${state === "waiting_on_you" ? "text-ink-secondary" : "text-ink-muted"}`}>
      {state === "waiting_on_you" ? <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-accent-default" /> : null}
      {t(`matters.state.${state}` as StringKey)}
    </span>
  );
}

export function StateBadge({ state }: { state: MatterState }) {
  return <Badge tone={STATE_TONE[state]}>{t(`matters.state.${state}` as StringKey)}</Badge>;
}

/** Each kind of change has a look, the same on the brief, the timeline and the week. */
export const KIND_MARK: Record<MatterEventKind, { shape: MarkShape; tone: MarkTone }> = {
  // The accent is kept for now and for what's unseen, so emails and replies stay in ink.
  started: { shape: "dot", tone: "ink" },
  joined: { shape: "ring", tone: "ink" },
  mail: { shape: "dot", tone: "ink" },
  sent: { shape: "ring", tone: "ink" },
  task: { shape: "diamond", tone: "warning" },
  due: { shape: "diamondRing", tone: "warning" },
  closed: { shape: "dot", tone: "success" },
  done: { shape: "dot", tone: "success" },
  reopened: { shape: "ring", tone: "warning" },
  moved: { shape: "ring", tone: "ink" },
};

export const kindLabel = (kind: MatterEventKind) => t(`matters.kind.${kind}` as StringKey);

/** The page's view and chosen matter live in the address, so a link or Back brings them back. */
export function useTodayView(): { view: TodayView; matter: number | null; go: (view: TodayView, matter?: number | null) => void } {
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const asked = params.get("view");
  const view = VIEWS.includes(asked as TodayView) ? (asked as TodayView) : "brief";
  const matter = Number(params.get("matter")) || null;
  const go = (next: TodayView, id: number | null = null) => {
    const query = new URLSearchParams({ view: next, ...(id ? { matter: String(id) } : {}) });
    router.replace(`${path}?${query.toString()}`, { scroll: false });
  };
  return { view, matter, go };
}

/** A due date as the person reads it, and whether it has passed. Dates are local days; times
 * are local times. */
export function useDue(): (when: string) => { text: string; overdue: boolean } {
  const day = useDateOnly();
  const moment = useDateTime();
  return (when) => {
    const hasTime = when.length > 10;
    const date = new Date(hasTime ? when : `${when}T23:59`);
    const overdue = date.getTime() < Date.now();
    const shown = hasTime ? moment(when) : day(when);
    return { text: overdue ? t("matters.overdue", { when: shown }) : t("matters.due", { when: shown }), overdue };
  };
}

/** Where a time falls: 0 at the start of the range, 1 at its end. */
export function placeIn(when: string, start: Date, days: number): number {
  const date = new Date(when.length > 10 ? when : `${when}T12:00`);
  return (date.getTime() - start.getTime()) / (days * 86_400_000);
}

/** Done, with Undo in the toast that says what closed with it. */
export function useMatterDoneWithUndo(): (matter: Pick<MatterRow, "id" | "title">) => void {
  const done = useMatterDone();
  const reopen = useMatterReopen();
  const toast = useToast();
  return (matter) =>
    done.mutate(matter.id, {
      onSuccess: ({ closed }) =>
        toast({
          title: closed ? tn("matters.done.toast", closed) : t("matters.done.toast.none"),
          description: matter.title,
          action: { label: t("matters.undo"), run: () => reopen.mutate(matter.id, { onSuccess: () => toast({ title: t("matters.reopened") }) }) },
        }),
      onError: (error) => toast({ title: error.message, tone: "danger" }),
    });
}

export function countsOf(matter: MatterRow): string {
  const parts = [tn("matters.emails", matter.emails ?? 0)];
  if ((matter.threads ?? 0) > 1) parts.push(tn("matters.threads", matter.threads ?? 0));
  if (matter.state === "waiting_on_others" && (matter.quiet_days ?? 0) > 0) parts.push(tn("matters.quiet", matter.quiet_days ?? 0));
  return parts.join(" · ");
}

/** The email a change came from: a click previews it over the page, Cmd or Ctrl and a click opens it. */
export function SourceLink({ source, testid, children }: { source: PreviewSource; testid?: string; children: React.ReactNode }) {
  const preview = useOpenSource();
  return (
    <a href={fullHref(source)} {...quickLook(() => preview.open(source), () => preview.openFull(source))} {...(testid ? { "data-testid": testid } : {})} className="focus-ring min-w-0 rounded-sm text-ink-secondary underline-offset-4 transition-colors duration-fast hover:text-ink-primary hover:underline">
      {children}
    </a>
  );
}

export function changeSource(change: MatterChange): PreviewSource | null {
  return change.source ?? null;
}
