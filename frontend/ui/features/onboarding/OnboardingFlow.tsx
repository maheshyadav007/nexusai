"use client";

import { PostyGuide } from "@/ui/shell/PostyGuide";
import { useRouter } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";
import { useHomeStatus } from "@/ui/client/home";
import { useFinishOnboarding, useOnboarding, useSetStep } from "@/ui/client/onboarding";
import { useMailStatus } from "@/ui/client/mail";
import { useSemantic } from "@/ui/client/semantic";
import { useStarterPrompts } from "@/ui/client/work";
import { AgentPresets } from "@/ui/features/settings/AgentSettings";
import { HomeChooser } from "@/ui/features/home/HomeChooser";
import { EmailConnector } from "@/ui/features/connectors/ConnectorsScreen";
import { LocalModelSettings } from "@/ui/features/settings/LocalModelSettings";
import { ProfileForm } from "@/ui/features/settings/ProfileForm";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Steps } from "@/ui/primitives/Motion";
import { t, type StringKey } from "@/ui/strings";

interface Step {
  id: string;
  label: StringKey;
  title: StringKey;
}

// Only what the app can't work without, or that's far easier now. The rest waits on Today.
const STEPS: readonly Step[] = [
  { id: "home", label: "setup.home.label", title: "setup.home.title" },
  { id: "profile", label: "setup.you.label", title: "setup.profile.title" },
  { id: "mail", label: "setup.mail.label", title: "setup.mail.title" },
  { id: "search", label: "setup.search.label", title: "setup.search.title" },
  { id: "permissions", label: "setup.agent.label", title: "setup.permissions.title" },
];

const NEEDS_RECOVERY = new Set(["missing", "locked", "damaged"]);

/** Nothing downloads until the person says so. Skipping just means search goes by keyword. */
function SearchStep() {
  return <LocalModelSettings brief bare />;
}

function Frame({ step, index, actions, children }: { step: Step; index: number; actions?: ReactNode; children: ReactNode }) {
  const seen = useRef(index);
  const forward = index >= seen.current;
  useEffect(() => {
    seen.current = index;
  }, [index]);
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface-page text-ink-primary">
      <header className="flex h-topbar shrink-0 items-center justify-between gap-5 px-5 md:px-6">
        <span className="text-lg font-medium">{t("app.name")}</span>
        <div className="flex items-center gap-3 text-sm text-ink-muted">
          <span className="hidden sm:inline">{t("setup.quick")}</span>
          <progress className="nx-progress w-rail-wide" aria-label={t("setup.progress")} max={STEPS.length} value={index + 1} />
          <span className="tabular-nums">{t("setup.stepCount", { current: index + 1, total: STEPS.length })}</span>
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto overscroll-contain lg:grid lg:grid-cols-5 lg:overflow-hidden">
        <aside className="relative flex min-h-drawer flex-col justify-between px-6 py-7 lg:col-span-2 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:px-7 lg:py-7">
          <PostyGuide prominent title={t(step.title)} message={`posty.setup.${step.id}` as StringKey} />
          <p className="mt-6 text-sm text-ink-muted">{t(index === STEPS.length - 1 ? "setup.lastStep" : "setup.time")}</p>
          <span aria-hidden className="absolute right-0 top-1/2 hidden h-popover w-px -translate-y-1/2 bg-line-subtle lg:block" />
        </aside>
        <section className="min-w-0 px-6 pb-7 pt-6 lg:col-span-3 lg:h-full lg:overflow-y-auto lg:px-7 lg:py-7">
          <div className="mx-auto w-full max-w-reading">
            <p className="mb-5 text-sm font-medium tracking-wide text-ink-muted">{t(step.label)}</p>
            <Steps step={step.id} forward={forward}>
              <section className="onboarding-fields flex flex-col gap-5">
                {children}
                {actions ? <footer className="flex items-center gap-3">{actions}</footer> : null}
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

  if (step.id === "profile") {
    return (
      <Frame step={step} index={index}>
        <ProfileForm compact onboarding actions={back} action={t("setup.next")} onSaved={goNext} />
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
      {step.id === "mail" ? <EmailConnector brief /> : null}
      {step.id === "search" ? <SearchStep /> : null}
      {step.id === "permissions" ? <AgentPresets /> : null}
    </Frame>
  );
}
