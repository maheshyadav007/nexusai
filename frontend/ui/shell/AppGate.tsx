"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useHomeStatus } from "@/ui/client/home";
import { useOnboarding } from "@/ui/client/onboarding";
import { useSettings } from "@/ui/client/settings";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";

/** Where this person should be right now, or null if they're allowed in the app. */
function useEntryRoute(): { route: string | null; pending: boolean; failed: boolean; retry: () => void } {
  const home = useHomeStatus();
  const onboarding = useOnboarding();
  const retry = () => void home.refetch();
  if (home.isError) return { route: null, pending: false, failed: true, retry };
  if (home.isPending) return { route: null, pending: true, failed: false, retry };
  if (home.data.state === "unset") return { route: "/welcome", pending: false, failed: false, retry };
  if (home.data.state === "missing" || home.data.state === "locked" || home.data.state === "damaged") return { route: "/recover", pending: false, failed: false, retry };
  if (onboarding.isError) return { route: null, pending: false, failed: true, retry: () => void onboarding.refetch() };
  if (onboarding.isPending) return { route: null, pending: true, failed: false, retry };
  return { route: onboarding.data.completed ? null : "/setup", pending: false, failed: false, retry };
}

function Waiting() {
  return (
    <div aria-busy className="mx-auto flex max-w-content flex-col gap-3 p-6">
      <Skeleton className="h-6 w-1/2" />
      <Skeleton />
    </div>
  );
}

function BackendDown({ retry }: { retry: () => void }) {
  return (
    <div className="mx-auto max-w-content p-6">
      <ErrorState title={t("gate.down.title")} description={t("gate.down.description")} onRetry={retry} />
    </div>
  );
}

/** Keeps the app behind a chosen Home and a finished setup. */
export function AppGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { route, pending, failed, retry } = useEntryRoute();
  useEffect(() => {
    if (route) router.replace(route);
  }, [route, router]);
  if (failed) return <BackendDown retry={retry} />;
  if (pending || route) return <Waiting />;
  return children;
}

/** The first page: sends each person to where they belong. */
export function EntryRedirect() {
  const router = useRouter();
  const { route, pending, failed, retry } = useEntryRoute();
  const settings = useSettings();
  const start = settings.data?.default_screen === "inbox" ? "/mail/inbox" : "/today";
  const waiting = pending || (!route && settings.isPending);
  useEffect(() => {
    if (!waiting && !failed) router.replace(route ?? start);
  }, [route, waiting, failed, start, router]);
  return failed ? <BackendDown retry={retry} /> : <Waiting />;
}
