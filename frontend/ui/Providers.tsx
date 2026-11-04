"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { EventsProvider } from "./client/events";
import { ToastProvider } from "./primitives/Toast";
import { DesktopFrame } from "./shell/DesktopFrame";
import { DefaultModel } from "./features/onboarding/DefaultModel";
import { ConnectionBanner } from "./shell/ConnectionBanner";
import { ThemeProvider } from "./theme/ThemeProvider";

export function Providers({ children }: { children: ReactNode }) {
  // Data changes arrive as events, so nothing refetches on a timer or on window focus.
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: Infinity, refetchOnWindowFocus: false, retry: 1 } },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <EventsProvider>
        <ThemeProvider>
          <ToastProvider>
            <DesktopFrame />
            <DefaultModel />
            <ConnectionBanner />
            {children}
          </ToastProvider>
        </ThemeProvider>
      </EventsProvider>
    </QueryClientProvider>
  );
}
