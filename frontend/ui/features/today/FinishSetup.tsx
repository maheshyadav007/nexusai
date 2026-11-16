"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";
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
import { Dialog } from "@/ui/primitives/Dialog";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { Progress } from "@/ui/primitives/Progress";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { t, type StringKey } from "@/ui/strings";

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
  const retry = useMutation({ mutationFn: () => command("mailAgent.retryLearning", {}), onSuccess: () => client.invalidateQueries({ queryKey: ["mail-organization"] }) });

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
  else if (learned) Object.assign(reading, { detail: t(state === "asking" ? "start.reading.asking" : "start.reading.done"), tone: state === "asking" ? "waiting" : "done" });
  else if (downloading) Object.assign(reading, { detail: t("start.reading.downloading", { done: (mail.data?.done ?? 0).toLocaleString(), total: (mail.data?.total ?? 0).toLocaleString() }), tone: "running" });
  else if (state === "learning") Object.assign(reading, { detail: t("start.reading.progress", { done: organization.data?.done ?? 0, total: organization.data?.total ?? 0 }), tone: "running" });
  steps.push(reading);

  const questions: Step = { id: "questions", title: "start.questions.title", detail: t("start.questions.later"), tone: "idle" };
  if (met) Object.assign(questions, { detail: t("start.questions.done"), tone: "done" });
  else if (meeting) Object.assign(questions, { detail: t("start.questions.open", { name: lead }), tone: "waiting", action: { label: "start.open", href: `/agent/sessions/${meeting.id}` } });
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

export function FinishSetup() {
  const onboarding = useOnboarding();
  const dismiss = useDismissChecklist();
  const lead = useLeadName();
  const { steps, loaded, failed } = useSteps();
  const [open, setOpen] = useState(false);
  const [welcome, setWelcome] = useState(false);
  const done = steps.filter((step) => step.tone === "done").length;
  // Hidden on request, except when reading failed: that has to stay where it can be retried.
  const showing = Boolean(loaded && onboarding.data?.completed && (failed || (!onboarding.data.checklist_dismissed && done < steps.length)));
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
          <Rise as="section" key="finish-setup" aria-label={t("start.title")} data-testid="finish-setup" className="flex flex-col gap-3 rounded-lg border border-line-subtle bg-surface-raised p-4">
            <header className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-md font-medium text-ink-primary">{t("start.title")}</h2>
                <p className="text-sm tabular-nums text-ink-muted">{t("finish.count", { done, total: steps.length })}</p>
              </div>
              <Button variant="quiet" onClick={() => dismiss.mutate(undefined)}>{t("finish.dismiss")}</Button>
            </header>
            <Progress label={t("start.title")} value={done} max={steps.length} />
            <StepList steps={steps} />
          </Rise>
        ) : null}
      </Presence>
    </>
  );
}
