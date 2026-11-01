"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { EventsProvider } from "./client/events";
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
          <ConnectionBanner />
          {children}
        </ThemeProvider>
      </EventsProvider>
    </QueryClientProvider>
  );
}
