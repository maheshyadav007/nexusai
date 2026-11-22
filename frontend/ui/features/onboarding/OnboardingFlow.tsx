"use client";

import { AssistantGuide } from "@/ui/shell/AssistantGuide";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useHomeStatus, useLeadName } from "@/ui/client/home";
import { useFinishOnboarding, useOnboarding, useSetStep } from "@/ui/client/onboarding";
import { useMailStatus } from "@/ui/client/mail";
import { useSemantic } from "@/ui/client/semantic";
import { useStarterPrompts } from "@/ui/client/work";
import { AgentPresets } from "@/ui/features/settings/AgentSettings";
import { HomeChooser } from "@/ui/features/home/HomeChooser";
import { WELCOME_PARAM } from "@/ui/features/today/FinishSetup";
import { EmailConnector } from "@/ui/features/connectors/ConnectorsScreen";
import { SortScreen } from "@/ui/features/mail/SortScreen";
import { LocalModelSettings } from "@/ui/features/settings/LocalModelSettings";
import { ProfileForm } from "@/ui/features/settings/ProfileForm";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Steps } from "@/ui/primitives/Motion";
import { t, type StringKey } from "@/ui/strings";

interface Step {
  id: string;
  label: StringKey;
  title: StringKey;
  formTitle: StringKey;
  formNote: StringKey;
}

// Only what the app can't work without, or that's far easier now. The rest waits on Today.
const STEPS: readonly Step[] = [
  { id: "home", label: "setup.home.label", title: "setup.home.title", formTitle: "setup.home.formTitle", formNote: "setup.home.formNote" },
  { id: "profile", label: "setup.you.label", title: "setup.profile.title", formTitle: "setup.profile.formTitle", formNote: "setup.profile.formNote" },
  { id: "mail", label: "setup.mail.label", title: "setup.mail.title", formTitle: "setup.mail.formTitle", formNote: "setup.mail.formNote" },
  // Right after mail and before search, so what the person keeps from the AI is never embedded.
  { id: "sort", label: "setup.sort.label", title: "setup.sort.label", formTitle: "setup.sort.label", formNote: "setup.sort.label" },
  { id: "search", label: "setup.search.label", title: "setup.search.title", formTitle: "setup.search.formTitle", formNote: "setup.search.formNote" },
  { id: "permissions", label: "setup.agent.label", title: "setup.permissions.title", formTitle: "setup.permissions.formTitle", formNote: "setup.permissions.formNote" },
];

// Every step's main button is as wide as the widest of these, so it stays put from step to step.
const SETUP_LABELS = () => [t("setup.skip"), t("setup.next"), t("setup.enter")];

const NEEDS_RECOVERY = new Set(["missing", "locked", "damaged"]);

/** Nothing downloads until the person says so. Skipping just means search goes by keyword. */
function SearchStep() {
  return <LocalModelSettings brief bare />;
}

/** Where setup is: the same bar on every step. */
function Topbar({ index }: { index: number }) {
  return (
    <header className="flex h-topbar shrink-0 items-center justify-between gap-5 px-6 lg:px-7">
      <span className="text-lg font-medium">{t("app.name")}</span>
      <div className="flex items-center gap-3 text-sm text-ink-muted">
        <span className="hidden sm:inline">{t("setup.quick")}</span>
        <progress className="nx-progress w-rail-wide" aria-label={t("setup.progress")} max={STEPS.length} value={index + 1} />
        <span className="tabular-nums">{t("setup.stepCount", { current: index + 1, total: STEPS.length })}</span>
      </div>
    </header>
  );
}

function Frame({ step, index, actions, children }: { step: Step; index: number; actions?: ReactNode; children: ReactNode }) {
  const seen = useRef(index);
  const lead = useLeadName();
  const main = useRef<HTMLElement>(null);
  const forward = index >= seen.current;
  useEffect(() => {
    seen.current = index;
    main.current?.scrollTo({ top: 0 });
  }, [index]);
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface-page text-ink-primary">
      <Topbar index={index} />
      <main ref={main} className="min-h-0 flex-1 overflow-y-auto overscroll-contain lg:grid lg:grid-cols-5 lg:overflow-hidden">
        <aside className="relative flex min-h-drawer flex-col justify-between px-6 py-6 lg:col-span-2 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:px-7 lg:py-7">
          <AssistantGuide prominent title={t(step.title, { name: lead })} message={`guide.setup.${step.id}` as StringKey} />
          <p className="mt-6 text-sm text-ink-muted">{t(index === STEPS.length - 1 ? "setup.lastStep" : "setup.time")}</p>
          <span aria-hidden className="absolute right-0 top-1/2 hidden h-popover w-px -translate-y-1/2 bg-line-subtle lg:block" />
        </aside>
        <section className="flex min-w-0 items-start px-6 py-6 lg:col-span-3 lg:h-full lg:overflow-y-auto lg:px-7 lg:py-7">
          {/* Top-aligned and at least the step's height, so what appears while a step works (a
              connection, a download) never moves the buttons; taller steps scroll. */}
          <div className="mx-auto flex min-h-onboarding w-full max-w-onboarding flex-col">
            <p className="mb-2 text-sm font-medium tracking-wide text-ink-muted">{t(step.label, { name: lead })}</p>
            <h2 className="font-serif text-title text-ink-primary">{t(step.formTitle, { name: lead })}</h2>
            <p className="mb-8 mt-2 text-md leading-relaxed text-ink-muted">{t(step.formNote)}</p>
            <Steps step={step.id} forward={forward}>
              <section className="onboarding-fields flex flex-1 flex-col gap-5">
                {children}
                {actions ? <footer className="mt-auto flex w-full items-center justify-between gap-3 pt-6">{actions}</footer> : null}
              </section>
            </Steps>
          </div>
        </section>
      </main>
    </div>
  );
}

export function OnboardingFlow() {
  const router = useRouter();
  const home = useHomeStatus();
  const onboarding = useOnboarding();
  const setStep = useSetStep();
  const finish = useFinishOnboarding();
  const starters = useStarterPrompts();
  const mail = useMailStatus();
  const semantic = useSemantic();
  // Skipping mail leaves the app with little to do, so it's confirmed rather than one click.
  const [confirmSkip, setConfirmSkip] = useState(false);
  // Finishing sends the person on with the welcome; the redirect for returning people waits.
  const finishing = useRef(false);

  const done = onboarding.data?.completed;
  useEffect(() => {
    if (home.data && NEEDS_RECOVERY.has(home.data.state)) router.replace("/recover");
    else if (done && !finishing.current) router.replace("/today");
  }, [home.data, done, router]);

  if (home.isError || onboarding.isError) {
    return (
      <div className="mx-auto max-w-content p-6">
        <ErrorState title={t("gate.down.title")} description={t("gate.down.description")} onRetry={() => void home.refetch()} />
      </div>
    );
  }
  if (!home.data || NEEDS_RECOVERY.has(home.data.state)) return <Skeleton className="h-6 w-full" />;

  const first = STEPS[0] as Step;
  if (home.data.state === "unset") {
    return (
      <Frame step={first} index={0}>
        <HomeChooser onboarding initialPath={home.data.default_path} action={t("setup.home.action")} onChosen={() => setStep.mutate((STEPS[1] as Step).id)} />
      </Frame>
    );
  }
  if (!onboarding.data || done) return <Skeleton className="h-6 w-full" />;

  // Home can't be revisited here, so a Home opened by an earlier run resumes at the next step.
  const found = STEPS.findIndex((item) => item.id === (onboarding.data.current_step === "model" ? "search" : onboarding.data.current_step));
  const index = found > 0 ? found : 1;
  const step = STEPS[index] as Step;
  const isLast = index === STEPS.length - 1;
  // With mail connected, setup waits for it: sorting needs all of it, and starts by itself.
  const downloading = step.id === "mail" && Boolean(mail.data?.account) && !mail.data?.history_finished;
  const goNext = () => {
    if (downloading) return;
    if (step.id === "mail" && !mail.data?.account && !confirmSkip) {
      setConfirmSkip(true);
      return;
    }
    setConfirmSkip(false);
    // Without mail there's nothing to sort.
    const next = STEPS[index + 1]?.id === "sort" && !mail.data?.account ? STEPS[index + 2] : STEPS[index + 1];
    if (next) setStep.mutate(next.id);
    else {
      // So the mail agent has something sensible to judge by, even if the person never edits it.
      starters.mutate(undefined);
      finishing.current = true;
      finish.mutate(undefined, { onSuccess: () => router.replace(`/today?${WELCOME_PARAM}`) });
    }
  };
  const back =
    index > 1 ? (
      <Button variant="quiet" onClick={() => setStep.mutate((STEPS[STEPS[index - 1]?.id === "sort" && !mail.data?.account ? index - 2 : index - 1] as Step).id)}>
        {t("setup.back")}
      </Button>
    ) : null;

  // The sorting page needs the whole width, so it has the setup bar and nothing else.
  if (step.id === "sort") {
    return (
      <div className="flex h-screen flex-col overflow-hidden bg-surface-page text-ink-primary">
        <Topbar index={index} />
        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto border-t border-line-subtle">
          <SortScreen onDone={goNext} onBack={() => setStep.mutate("mail")} />
        </main>
      </div>
    );
  }
  if (step.id === "profile") {
    return (
      <Frame step={step} index={index}>
        <ProfileForm compact onboarding actions={back} action={t("setup.next")} sizedFor={SETUP_LABELS()} onSaved={goNext} />
      </Frame>
    );
  }
  return (
    <Frame
      step={step}
      index={index}
      actions={
        <>
          {back ?? <span aria-hidden />}
          <Button variant="primary" loading={setStep.isPending || finish.isPending} disabled={downloading} onClick={goNext} sizedFor={SETUP_LABELS()}>
            {t(isLast ? "setup.enter" : (step.id === "mail" && !mail.data?.account) || (step.id === "search" && !semantic.data?.ready && !semantic.data?.models.some((row) => row.state === "downloading")) ? "setup.skip" : "setup.next")}
          </Button>
        </>
      }
    >
      {step.id === "mail" ? <EmailConnector brief /> : null}
      {step.id === "mail" ? (
        <Dialog title={t("setup.mail.skip.title")} description={t("setup.mail.skip.description")} open={confirmSkip} onOpenChange={setConfirmSkip}>
          <footer className="flex justify-end gap-2">
            <Button variant="quiet" onClick={goNext}>{t("setup.mail.skip.confirm")}</Button>
            <Button variant="primary" onClick={() => setConfirmSkip(false)}>{t("setup.mail.skip.connect")}</Button>
          </footer>
        </Dialog>
      ) : null}
      {step.id === "search" ? <SearchStep /> : null}
      {step.id === "permissions" ? <AgentPresets /> : null}
    </Frame>
  );
}
