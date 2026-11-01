"use client";

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { EVENTS_URL, latestSeq } from "./api";
import type { AppEvent } from "./contracts.generated";

/** Which saved query goes out of date when an event happens. Screens never poll. */
const INVALIDATES: Record<string, readonly string[]> = {
  "settings.changed": ["settings"],
};

type Listener = (event: AppEvent) => void;

interface EventsValue {
  connected: boolean;
  subscribe: (listener: Listener) => () => void;
}

const EventsContext = createContext<EventsValue | null>(null);

export function EventsProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const listeners = useRef(new Set<Listener>());
  const [connected, setConnected] = useState(true);

  useEffect(() => {
    // EventSource reconnects by itself and sends Last-Event-ID, so nothing is missed.
    let source: EventSource | null = null;
    let cancelled = false;
    void latestSeq().then((seq) => {
      if (cancelled) return;
      source = new EventSource(`${EVENTS_URL}?since=${seq}`);
      source.onopen = () => setConnected(true);
      source.onerror = () => setConnected(false);
      source.onmessage = (message) => {
        const event = JSON.parse(message.data as string) as AppEvent;
        for (const key of INVALIDATES[event.type] ?? []) void client.invalidateQueries({ queryKey: [key] });
        for (const listener of listeners.current) listener(event);
      };
    });
    return () => {
      cancelled = true;
      source?.close();
    };
  }, [client]);

  const subscribe = (listener: Listener) => {
    listeners.current.add(listener);
    return () => void listeners.current.delete(listener);
  };

  return <EventsContext.Provider value={{ connected, subscribe }}>{children}</EventsContext.Provider>;
}

export function useEvents(): EventsValue {
  const value = useContext(EventsContext);
  if (!value) throw new Error("useEvents must be used inside EventsProvider");
  return value;
}
