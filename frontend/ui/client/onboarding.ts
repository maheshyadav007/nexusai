"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { command, query } from "./api";
import type { OnboardingState, Profile } from "./contracts.generated";
import { useHomeReady } from "./home";

export function useOnboarding() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["onboarding"], queryFn: () => query("onboarding.state", {}), enabled: ready });
}

function useOnboardingCommand<T>(run: (input: T) => Promise<OnboardingState>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: run, onSuccess: (state) => client.setQueryData(["onboarding"], state) });
}

export const useSetStep = () => useOnboardingCommand((step: string) => command("onboarding.setStep", { step }));
export const useFinishOnboarding = () => useOnboardingCommand(() => command("onboarding.finish", {}));
export const useDismissChecklist = () => useOnboardingCommand(() => command("onboarding.dismissChecklist", {}));

export function useProfile() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["profile"], queryFn: () => query("profile.get", {}), enabled: ready });
}

export function useSaveProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (profile: Profile) => command("profile.update", profile),
    onSuccess: (profile) => client.setQueryData(["profile"], profile),
  });
}
