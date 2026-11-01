"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useHomeStatus } from "@/ui/client/home";
import { useFinishOnboarding, useOnboarding, useSetStep } from "@/ui/client/onboarding";
import { HomeChooser } from "@/ui/features/home/HomeChooser";
import { AccountSettings } from "@/ui/features/settings/AccountSettings";
import { AppearanceSettings } from "@/ui/features/settings/AppearanceSettings";
import { ModelSettings } from "@/ui/features/settings/ModelSettings";
import { ProfileForm } from "@/ui/features/settings/ProfileForm";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Stepper } from "@/ui/primitives/Stepper";
import { t, type StringKey } from "@/ui/strings";

interface Step {
  id: string;
  label: StringKey;
  title: StringKey;
  description: StringKey;
  optional?: boolean;
}

// The setup interview, priorities, PST import and permissions join as their stages arrive.
const STEPS: readonly Step[] = [
  { id: "home", label: "setup.home.label", title: "setup.home.title", description: "setup.home.description" },
  { id: "theme", label: "setup.theme.label", title: "setup.theme.title", description: "setup.theme.description" },
  { id: "profile", label: "setup.profile.label", title: "setup.profile.title", description: "setup.profile.description" },
  { id: "mail", label: "setup.mail.label", title: "setup.mail.title", description: "setup.mail.description", optional: true },
  { id: "model", label: "setup.model.label", title: "setup.model.title", description: "setup.model.description", optional: true },
];

function Frame({ step, index, actions, children }: { step: Step; index: number; actions?: ReactNode; children: ReactNode }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-content flex-col gap-6 p-6 text-ink-primary">
      <header className="flex flex-col gap-4">
        <span className="text-lg font-medium">{t("app.name")}</span>
        <Stepper label={t("setup.progress")} steps={STEPS.map((item) => t(item.label))} current={index} />
      </header>
      <section className="flex flex-col gap-5">
        <div>
          <h1 className="font-serif text-display">{t(step.title)}</h1>
          <p className="mt-2 max-w-popover text-md text-ink-secondary">{t(step.description)}</p>
        </div>
        {children}
      </section>
      {actions ? <footer className="flex items-center gap-3">{actions}</footer> : null}
    </main>
  );
}

export function OnboardingFlow() {
  const router = useRouter();
  const home = useHomeStatus();
  const onboarding = useOnboarding();
  const setStep = useSetStep();
  const finish = useFinishOnboarding();

  const done = onboarding.data?.completed;
  useEffect(() => {
    if (home.data?.state === "missing") router.replace("/recover");
    else if (done) router.replace("/today");
  }, [home.data, done, router]);

  if (home.isError || onboarding.isError) {
    return (
      <div className="mx-auto max-w-content p-6">
        <ErrorState title={t("gate.down.title")} description={t("gate.down.description")} onRetry={() => void home.refetch()} />
      </div>
    );
  }
  if (!home.data || home.data.state === "missing") return <Skeleton className="h-6 w-full" />;

  const first = STEPS[0] as Step;
  if (home.data.state === "unset") {
    return (
      <Frame step={first} index={0}>
        <HomeChooser initialPath={home.data.default_path} action={t("setup.home.action")} onChosen={() => setStep.mutate("theme")} />
      </Frame>
    );
  }
  if (!onboarding.data || done) return <Skeleton className="h-6 w-full" />;

  // Home can't be revisited here, so a Home opened by an earlier run resumes at the next step.
  const found = STEPS.findIndex((item) => item.id === onboarding.data.current_step);
  const index = found > 0 ? found : 1;
  const step = STEPS[index] as Step;
  const isLast = index === STEPS.length - 1;
  const goNext = () => {
    const next = STEPS[index + 1];
    if (next) setStep.mutate(next.id);
    else finish.mutate(undefined, { onSuccess: () => router.replace("/today") });
  };
  const back =
    index > 1 ? (
      <Button variant="quiet" onClick={() => setStep.mutate((STEPS[index - 1] as Step).id)}>
        {t("setup.back")}
      </Button>
    ) : null;

  if (step.id === "profile") {
    return (
      <Frame step={step} index={index} actions={back}>
        <ProfileForm action={t("setup.next")} onSaved={goNext} />
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
            {t(isLast ? "setup.enter" : "setup.next")}
          </Button>
        </>
      }
    >
      {step.id === "theme" ? <AppearanceSettings /> : null}
      {step.id === "mail" ? <AccountSettings /> : null}
      {step.id === "model" ? <ModelSettings /> : null}
    </Frame>
  );
}
