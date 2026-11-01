import type { ReactNode } from "react";
import { ErrorBoundary } from "@/ui/primitives/ErrorBoundary";
import { t } from "@/ui/strings";
import type { Activity } from "./ActivityIsland";
import { BrowserAlerts } from "./BrowserAlerts";
import { NavSidebar } from "./NavSidebar";
import { TopBar } from "./TopBar";

export function AppShell({ activities, counts, children }: { activities?: readonly Activity[]; counts?: Readonly<Record<string, number>>; children: ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden bg-surface-page">
      <a href="#main" className="focus-ring sr-only rounded-md bg-surface-raised p-2 text-md text-ink-primary focus:not-sr-only focus:absolute focus:z-50">
        {t("nav.skip")}
      </a>
      <BrowserAlerts />
      <NavSidebar {...(counts ? { counts } : {})} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar {...(activities ? { activities } : {})} />
        <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto outline-none">
          <ErrorBoundary>{children}</ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
