"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { command, query } from "@/ui/client/api";
import { useHomeReady, useLeadName } from "@/ui/client/home";
import { useMailStatus } from "@/ui/client/mail";
import { useModelStatus } from "@/ui/client/models";
import { useDismissChecklist, useOnboarding } from "@/ui/client/onboarding";
import { useSessions } from "@/ui/client/sessions";
import { useAgentName, useToday } from "@/ui/client/work";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { SearchProgress } from "@/ui/features/settings/LocalModelSettings";
import { Button } from "@/ui/primitives/Button";
import { Pressable } from "@/ui/primitives/Pressable";
import { Tooltip } from "@/ui/primitives/Tooltip";
import { useSidebarCollapsed } from "@/ui/shell/NavSidebar";
import { Dialog } from "@/ui/primitives/Dialog";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { t, tn, type StringKey } from "@/ui/strings";

type Tone = "done" | "running" | "waiting" | "failed" | "idle";

interface Step {
  id: string;
  title: StringKey;
  detail: string;
  tone: Tone;
  action?: { label: StringKey; href?: string; run?: () => void; loading?: boolean };
  extra?: React.ReactNode;
}

/** Setup hands over to Today with this, so the welcome opens once, right after setup, and never
 * again on a reload, another window or another browser. */
export const WELCOME_PARAM = "welcome";

/** Everything that happens after setup, in one place and in the lead's voice: what it's doing,
 * the one thing it needs from the person, and when the first brief comes. Only what's required:
 * optional extras live in Settings. Gone once all of it is done. */
function useSteps(): { steps: Step[]; loaded: boolean; failed: boolean } {
  const ready = useHomeReady();
  const lead = useLeadName();
  const agentName = useAgentName();
  const mail = useMailStatus();
  const model = useModelStatus();
  const sessions = useSessions("");
  const today = useToday();
  const assistant = useAssistant();
  const client = useQueryClient();
  const organization = useQuery({ queryKey: ["mail-organization"], queryFn: () => query("mail.organization", {}), enabled: ready, refetchInterval: 5000 });
  const sorting = useQuery({ queryKey: ["mail-sort"], queryFn: () => query("mail.sort.get", {}), enabled: ready });
  const retry = useMutation({ mutationFn: () => command("mailAgent.retryLearning", {}), onSuccess: () => client.invalidateQueries({ queryKey: ["mail-organization"] }) });
  // Mail that wasn't sorted can leave a few unsure groups. Their guesses are kept in one press.
  const keep = useMutation({ mutationFn: () => command("mail.learning.finish", { importance: {} }), onSuccess: () => Promise.all(["mail-organization", "threads", "today"].map((key) => client.invalidateQueries({ queryKey: [key] }))) });

  const hasMail = Boolean(mail.data?.account);
  const hasModel = Boolean(model.data?.connected);
  const state = organization.data?.state ?? "idle";
  const learned = hasMail && (state === "done" || state === "asking");
  const meetings = (sessions.data?.sessions ?? []).filter((row) => row.agent === "interview");
  const met = meetings.some((row) => row.status === "done");
  const meeting = meetings.find((row) => row.status !== "done");
  const briefed = Boolean(today.data?.prep_at);
  const downloading = (mail.data?.total ?? 0) > (mail.data?.done ?? 0);

  const steps: Step[] = [];
  if (!hasMail) steps.push({ id: "mail", title: "start.mail.title", detail: t("start.mail.detail", { name: lead }), tone: "waiting", action: { label: "start.connect", href: "/connectors?connector=email" } });
  if (!hasModel) steps.push({ id: "model", title: "start.model.title", detail: t("start.model.detail", { name: lead }), tone: "waiting", action: { label: "start.connect", href: "/settings?section=models" } });

  const reading: Step = { id: "reading", title: "start.reading.title", detail: t("start.reading.waiting"), tone: "idle", extra: <SearchProgress /> };
  if (!hasMail) reading.detail = t("start.reading.needsMail");
  else if (state === "failed") Object.assign(reading, { detail: t("start.reading.failed"), tone: "failed", action: { label: "start.retry", run: () => retry.mutate(), loading: retry.isPending }, extra: retry.error ? <p role="alert" className="text-sm text-status-danger">{retry.error.message}</p> : null });
  else if (state === "asking") Object.assign(reading, { detail: t("start.reading.asking", { name: lead }), tone: "waiting", action: { label: "start.reading.keep", run: () => keep.mutate(), loading: keep.isPending } });
  else if (learned) Object.assign(reading, { detail: t("start.reading.done"), tone: "done" });
  else if (downloading) Object.assign(reading, { detail: t("start.reading.downloading", { done: (mail.data?.done ?? 0).toLocaleString(), total: (mail.data?.total ?? 0).toLocaleString() }), tone: "running" });
  // Reading waits until the person has sorted, so the AI never reads what they keep from it.
  else if (sorting.data?.state === "ready" || sorting.data?.state === "preparing") Object.assign(reading, { detail: t("start.reading.sorting", { name: lead }), tone: "waiting", action: { label: "mail.sort.card.open", href: "/mail/sort" } });
  else if (state === "learning") Object.assign(reading, { detail: t("start.reading.progress", { done: organization.data?.done ?? 0, total: organization.data?.total ?? 0 }), tone: "running" });
  steps.push(reading);

  const questions: Step = { id: "questions", title: "start.questions.title", detail: t("start.questions.later"), tone: "idle" };
  if (met) Object.assign(questions, { detail: t("start.questions.done"), tone: "done" });
  else if (meeting) Object.assign(questions, { detail: t("start.questions.open", { name: lead }), tone: "waiting", action: { label: "start.open", href: `/agent/sessions/${meeting.id}` } });
  // Once the mail is read it starts by itself, with questions about that mail. A button before
  // then started a second meeting on top of the one that followed.
  else if (hasModel && hasMail && !learned && state !== "failed") Object.assign(questions, { detail: t("start.questions.after", { name: lead }), tone: "idle" });
  else if (hasModel) Object.assign(questions, { detail: t("start.questions.ready"), tone: "waiting", action: { label: "start.begin", run: () => assistant.start({ title: t("setup.interview.label", { agent: agentName("interview") }), agent: "interview" }) } });
  steps.push(questions);

  steps.push(briefed ? { id: "brief", title: "start.brief.title", detail: t("start.brief.done"), tone: "done" } : { id: "brief", title: "start.brief.title", detail: t("start.brief.waiting"), tone: "idle" });
  return { steps, loaded: Boolean(mail.data && model.data && organization.data && sessions.data && today.data), failed: hasMail && state === "failed" };
}

function StepList({ steps }: { steps: Step[] }) {
  return (
    <ol className="flex flex-col">
      {steps.map((step) => (
        <li key={step.id} data-testid="start-step" className="flex items-start gap-3 border-b border-line-subtle py-3 last:border-b-0">
          <span className="pt-2">
            <StatusDot tone={step.tone} />
          </span>
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="text-md text-ink-primary">{t(step.title)}</span>
            <span role={step.tone === "failed" ? "alert" : undefined} className="text-sm text-ink-muted">{step.detail}</span>
            {step.tone === "running" || step.id === "reading" ? step.extra : null}
          </span>
          {step.action ? (
            step.action.href ? (
              <Link href={step.action.href} className="focus-ring shrink-0 rounded-md px-2 py-1 text-md text-accent-primary hover:bg-surface-sunken">
                {t(step.action.label)}
              </Link>
            ) : (
              <Button className="shrink-0" loading={step.action.loading ?? false} onClick={step.action.run}>
                {t(step.action.label)}
              </Button>
            )
          ) : null}
        </li>
      ))}
    </ol>
  );
}

// Without these nothing else can happen, so they keep setup on Today: no Later.
const NEEDED = new Set(["mail", "model"]);

/** Where setup stands, for Today's strip and the sidebar's row: how far along, what's left, and
 *  whether it's on Today or waiting in the sidebar after Later. */
export function useSetup() {
  const onboarding = useOnboarding();
  const { steps, loaded, failed } = useSteps();
  const done = steps.filter((step) => step.tone === "done").length;
  const needed = steps.some((step) => NEEDED.has(step.id) && step.tone !== "done");
  const unfinished = Boolean(loaded && onboarding.data?.completed && done < steps.length);
  // Later moves it to the sidebar, except when reading failed or something needed is missing.
  const onToday = unfinished && (failed || needed || !onboarding.data?.checklist_dismissed);
  return { steps, done, total: steps.length, failed, needed, onToday, inSidebar: unfinished && !onToday };
}

export function FinishSetup() {
  const dismiss = useDismissChecklist();
  const lead = useLeadName();
  const { steps, done, total, failed, needed, onToday: showing } = useSetup();
  const [open, setOpen] = useState(false);
  const [welcome, setWelcome] = useState(false);
  // Only what's left, one action each; with something needed missing, just that first.
  const left = steps.filter((step) => step.tone !== "done");
  const first = needed ? left.filter((step) => NEEDED.has(step.id) || step.tone === "failed") : left;
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (!params.has(WELCOME_PARAM)) return;
    setWelcome(true);
    params.delete(WELCOME_PARAM);
    window.history.replaceState(null, "", `${window.location.pathname}${params.size ? `?${params}` : ""}`);
  }, []);
  useEffect(() => {
    if (welcome && showing) {
      setOpen(true);
      setWelcome(false);
    }
  }, [welcome, showing]);
  const close = (next: boolean) => setOpen(next);
  return (
    <>
      <Dialog title={t("start.welcome.title", { name: lead })} description={t("start.welcome.description")} open={open} onOpenChange={close}>
        <StepList steps={steps} />
        <footer className="mt-4 flex justify-end">
          <Button variant="primary" onClick={() => close(false)}>{t("start.welcome.close")}</Button>
        </footer>
      </Dialog>
      <Presence>
        {showing ? (
          <Rise as="section" key="finish-setup" aria-label={t("finish.strip", { done, total })} data-testid="finish-setup" className={`flex flex-col gap-3 rounded-lg border bg-surface-raised p-4 ${needed || failed ? "border-accent-default/40" : "border-line-subtle"}`}>
            <header className="flex items-center justify-between gap-3">
              <h2 className="text-md font-medium tabular-nums text-ink-primary">{t("finish.strip", { done, total })}</h2>
              {needed || failed ? null : <Button onClick={() => dismiss.mutate(false)}>{t("finish.later")}</Button>}
            </header>
            <ol aria-hidden className="grid grid-flow-col gap-1">
              {steps.map((step, index) => <li key={step.id} className={`h-1 rounded-full ${index < done ? "bg-status-success" : "bg-line-subtle"}`} />)}
            </ol>
            <StepList steps={first} />
            {first.length < left.length ? <p className="text-sm text-ink-muted">{tn("finish.more", left.length - first.length)}</p> : null}
          </Rise>
        ) : null}
      </Presence>
    </>
  );
}

/** Setup waiting after Later: how far along, and a press brings it back to Today. */
export function SetupRow() {
  const collapsed = useSidebarCollapsed();
  const setup = useSetup();
  const back = useDismissChecklist();
  const router = useRouter();
  if (!setup.inSidebar) return null;
  const count = t("nav.setup.count", { done: setup.done, total: setup.total });
  const ring = (
    <svg aria-hidden viewBox="0 0 36 36" className="h-4 w-4 shrink-0 -rotate-90">
      <circle cx="18" cy="18" r="14" fill="none" strokeWidth="5" className="stroke-line-subtle" />
      <circle cx="18" cy="18" r="14" fill="none" strokeWidth="5" className="stroke-status-success" strokeDasharray={`${(88 * setup.done) / Math.max(1, setup.total)} 88`} />
    </svg>
  );
  const open = () => back.mutate(true, { onSuccess: () => router.push("/today") });
  return (
    <li data-testid="nav-setup" className="mt-1">
      <Tooltip content={t("nav.setup.about")} side="right">
        <Pressable onClick={open} aria-label={`${t("nav.setup")} ${count}`} className={`focus-ring press flex w-full items-center gap-2 rounded-md px-2 py-1 text-md text-ink-secondary hover:bg-surface-raised hover:text-ink-primary ${collapsed ? "justify-center" : ""}`}>
          {ring}
          {collapsed ? null : <><span className="flex-1 text-left">{t("nav.setup")}</span><span className="text-sm tabular-nums text-ink-muted">{count}</span></>}
        </Pressable>
      </Tooltip>
    </li>
  );
}
