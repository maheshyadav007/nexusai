"use client";

import { PostyGuide } from "@/ui/shell/PostyGuide";
import { useRouter } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";
import { useHomeStatus, useRecoveryKey } from "@/ui/client/home";
import { PendingRecoveryKey } from "@/ui/features/home/RecoveryKey";
import { useFinishOnboarding, useOnboarding, useSetStep } from "@/ui/client/onboarding";
import { useMailStatus } from "@/ui/client/mail";
import { useModelStatus } from "@/ui/client/models";
import { useSemantic } from "@/ui/client/semantic";
import { useStarterPrompts } from "@/ui/client/work";
import { AgentPresets } from "@/ui/features/settings/AgentSettings";
import { HomeChooser } from "@/ui/features/home/HomeChooser";
import { EmailConnector } from "@/ui/features/connectors/ConnectorsScreen";
import { AppearanceSettings } from "@/ui/features/settings/AppearanceSettings";
import { LocalModelSettings, SearchModelChoice } from "@/ui/features/settings/LocalModelSettings";
import { ProfileForm } from "@/ui/features/settings/ProfileForm";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Steps } from "@/ui/primitives/Motion";
import { Stepper, StepRail } from "@/ui/primitives/Stepper";
import { t, type StringKey } from "@/ui/strings";

interface Step {
  id: string;
  label: StringKey;
  title: StringKey;
  description: StringKey;
}

// Only what the app can't work without, or that's far easier now. The rest waits on Today.
const STEPS: readonly Step[] = [
  { id: "home", label: "setup.home.label", title: "setup.home.title", description: "setup.home.description" },
  { id: "recovery", label: "setup.recovery.label", title: "setup.recovery.title", description: "setup.recovery.description" },
  { id: "profile", label: "setup.you.label", title: "setup.profile.title", description: "setup.profile.description" },
  { id: "mail", label: "setup.mail.label", title: "setup.mail.title", description: "setup.mail.description" },
  { id: "search", label: "setup.search.label", title: "setup.search.title", description: "setup.search.description" },
  { id: "permissions", label: "setup.agent.label", title: "setup.permissions.title", description: "setup.permissions.description" },
];

const NEEDS_RECOVERY = new Set(["missing", "locked", "damaged"]);

/** Comes right after Home, so nobody's mail is stored before they hold the way back to it. */
function RecoveryStep({ step, index, back, onDone }: { step: Step; index: number; back: ReactNode; onDone: () => void }) {
  const key = useRecoveryKey();
  const pending = key.data?.pending;
  return (
    <Frame
      step={step}
      index={index}
      actions={
        pending ? (
          back
        ) : (
          <>
            {back}
            <Button variant="primary" disabled={!key.isSuccess} onClick={onDone}>
              {t("setup.next")}
            </Button>
          </>
        )
      }
    >
      {key.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {key.isError ? <ErrorState title={t("recovery.error")} onRetry={() => void key.refetch()} /> : null}
      {pending ? <PendingRecoveryKey value={pending} action={t("setup.next")} onSaved={onDone} /> : null}
      {key.isSuccess && !pending ? <p className="text-md text-ink-secondary">{t("recovery.alreadySaved")}</p> : null}
    </Frame>
  );
}

/** Nothing downloads until the person says so. Skipping just means search goes by keyword. */
function SearchStep() {
  return (
    <div className="flex flex-col gap-4">
      <SearchModelChoice />
      <LocalModelSettings brief />
    </div>
  );
}

/** Which earlier steps were passed without being done, so they aren't shown as finished. */
function useSkippedSteps(): ReadonlySet<number> {
  const mail = useMailStatus();
  const model = useModelStatus();
  const semantic = useSemantic();
  const skipped: Record<string, boolean> = {
    mail: Boolean(mail.data) && !mail.data?.account,
    model: Boolean(model.data) && !model.data?.connected,
    search: Boolean(semantic.data) && !semantic.data?.ready && !semantic.data?.models.some((row) => row.state === "downloading"),
  };
  return new Set(STEPS.flatMap((item, index) => (skipped[item.id] ? [index] : [])));
}

function Frame({ step, index, actions, children }: { step: Step; index: number; actions?: ReactNode; children: ReactNode }) {
  const skipped = useSkippedSteps();
  const seen = useRef(index);
  const forward = index >= seen.current;
  useEffect(() => {
    seen.current = index;
  }, [index]);
  return (
    <div className="flex h-screen overflow-hidden bg-surface-page text-ink-primary">
      <aside className="hidden h-full w-sidebar shrink-0 flex-col gap-6 overflow-y-auto overscroll-contain border-r border-line-subtle p-5 lg:flex">
        <span className="text-lg font-medium">{t("app.name")}</span>
        <StepRail label={t("setup.progress")} steps={STEPS.map((item) => t(item.label))} current={index} skipped={skipped} skippedLabel={t("setup.skipped")} />
        <p className="mt-auto text-sm text-ink-muted">{t("setup.time")}</p>
      </aside>
      <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain p-4 md:p-5">
        <header className="flex flex-col gap-4 lg:hidden">
          <span className="text-lg font-medium">{t("app.name")}</span>
          <Stepper label={t("setup.progress")} steps={STEPS.map((item) => t(item.label))} current={index} skipped={skipped} />
        </header>
        <div className={`mx-auto w-full ${step.id === "profile" ? "max-w-content py-2" : "max-w-reading py-4"}`}>
          <Steps step={step.id} forward={forward}>
            <section className={`flex flex-col ${step.id === "profile" ? "gap-3" : "gap-5"}`}>
              <div>
                <h1 className="font-serif text-display">{t(step.title)}</h1>
                <p className="mt-2 text-md text-ink-secondary">{t(step.description)}</p>
              </div>
              <PostyGuide message={`posty.setup.${step.id}` as StringKey} />
              {children}
              {actions ? <footer className="flex items-center gap-3">{actions}</footer> : null}
            </section>
          </Steps>
        </div>
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

  const done = onboarding.data?.completed;
  useEffect(() => {
    if (home.data && NEEDS_RECOVERY.has(home.data.state)) router.replace("/recover");
    else if (done) router.replace("/today");
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
        <HomeChooser initialPath={home.data.default_path} action={t("setup.home.action")} onChosen={() => setStep.mutate((STEPS[1] as Step).id)} />
      </Frame>
    );
  }
  if (!onboarding.data || done) return <Skeleton className="h-6 w-full" />;

  // Home can't be revisited here, so a Home opened by an earlier run resumes at the next step.
  const found = STEPS.findIndex((item) => item.id === (onboarding.data.current_step === "model" ? "search" : onboarding.data.current_step));
  const index = found > 0 ? found : 1;
  const step = STEPS[index] as Step;
  const isLast = index === STEPS.length - 1;
  const goNext = () => {
    const next = STEPS[index + 1];
    if (next) setStep.mutate(next.id);
    else {
      // So the mail agent has something sensible to judge by, even if the person never edits it.
      starters.mutate(undefined);
      finish.mutate(undefined, { onSuccess: () => router.replace("/today") });
    }
  };
  const back =
    index > 1 ? (
      <Button variant="quiet" onClick={() => setStep.mutate((STEPS[index - 1] as Step).id)}>
        {t("setup.back")}
      </Button>
    ) : null;

  if (step.id === "recovery") {
    return <RecoveryStep step={step} index={index} back={back} onDone={goNext} />;
  }
  if (step.id === "profile") {
    return (
      <Frame step={step} index={index}>
        <AppearanceSettings brief />
        <ProfileForm compact actions={back} action={t("setup.next")} onSaved={goNext} />
      </Frame>
    );
  }
  return (
    <Frame
      step={step}
      index={index}
      actions={
        <>
          {back}
          <Button variant="primary" loading={setStep.isPending || finish.isPending} onClick={goNext}>
            {t(isLast ? "setup.enter" : (step.id === "mail" && !mail.data?.account) || (step.id === "search" && !semantic.data?.ready && !semantic.data?.models.some((row) => row.state === "downloading")) ? "setup.skip" : "setup.next")}
          </Button>
        </>
      }
    >
      {step.id === "mail" ? <EmailConnector /> : null}
      {step.id === "search" ? <SearchStep /> : null}
      {step.id === "permissions" ? <AgentPresets /> : null}
    </Frame>
  );
}
