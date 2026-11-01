"use client";

import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { EVENTS_URL, latestSeq } from "./api";
import type { AppEvent } from "./contracts.generated";
import { useHomeStatus } from "./home";

/** Which saved query goes out of date when an event happens. Screens never poll. */
const INVALIDATES: Record<string, readonly string[]> = {
  "settings.changed": ["settings"],
  "models.changed": ["models", "models-available"],
  "onboarding.changed": ["onboarding"],
  "profile.changed": ["profile"],
  "sidebar.changed": ["sidebar"],
  "mail.changed": ["threads", "thread", "mail-status", "search", "documents", "panel-results"],
  "mail.syncChanged": ["mail-status"],
  "mail.accountsChanged": ["mail-accounts", "mail-status", "threads"],
  "thread.updated": ["threads", "thread"],
  "drafts.changed": ["drafts"],
  "rules.changed": ["rules"],
  "documents.changed": ["documents", "panel-results"],
  "document.indexed": ["documents", "search"],
  "pst.progress": ["pst", "mail-status"],
  "panels.changed": ["panels"],
  "notifications.changed": ["notifications"],
};

type Listener = (event: AppEvent) => void;

/**
 * Reads a query again. It's cancelled first because TanStack won't restart a first load when it's
 * invalidated, and that load may have read the old value just before the change.
 */
async function refresh(client: QueryClient, filters?: { queryKey: readonly string[] }) {
  await client.cancelQueries(filters);
  await client.invalidateQueries(filters);
}

interface EventsValue {
  connected: boolean;
  subscribe: (listener: Listener) => () => void;
}

const EventsContext = createContext<EventsValue | null>(null);

export function EventsProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const listeners = useRef(new Set<Listener>());
  const [connected, setConnected] = useState(true);
  const home = useHomeStatus();
  // Events need an open Home. Until then, the only question is whether the backend answers.
  const ready = home.data?.state === "ready";
  const reachable = !home.isError;

  useEffect(() => {
    if (!ready) {
      setConnected(reachable);
      return;
    }
    // EventSource reconnects by itself and sends Last-Event-ID, so nothing is missed.
    let source: EventSource | null = null;
    let cancelled = false;
    void latestSeq().then((seq) => {
      if (cancelled) return;
      source = new EventSource(`${EVENTS_URL}?since=${seq}`);
      source.onopen = () => {
        setConnected(true);
        // Anything could have changed before this connection opened.
        void refresh(client);
      };
      source.onerror = () => setConnected(false);
      source.onmessage = (message) => {
        const event = JSON.parse(message.data as string) as AppEvent;
        for (const key of INVALIDATES[event.type] ?? []) void refresh(client, { queryKey: [key] });
        for (const listener of listeners.current) listener(event);
      };
    });
    return () => {
      cancelled = true;
      source?.close();
    };
  }, [client, ready, reachable]);

  const subscribe = useCallback((listener: Listener) => {
    listeners.current.add(listener);
    return () => void listeners.current.delete(listener);
  }, []);

  return <EventsContext.Provider value={{ connected, subscribe }}>{children}</EventsContext.Provider>;
}

export function useEvents(): EventsValue {
  const value = useContext(EventsContext);
  if (!value) throw new Error("useEvents must be used inside EventsProvider");
  return value;
}
