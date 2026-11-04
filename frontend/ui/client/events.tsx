"use client";

import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { EVENTS_URL, latestSeq } from "./api";
import type { AppEvent } from "./contracts.generated";
import { useHomeStatus } from "./home";
import type { GenerationState } from "./contracts.generated";

/** Which saved query goes out of date when an event happens. Screens never poll. */
const INVALIDATES: Record<string, readonly string[]> = {
  "settings.changed": ["settings"],
  "models.changed": ["models", "models-available"],
  "onboarding.changed": ["onboarding"],
  "profile.changed": ["profile"],
  "sidebar.changed": ["sidebar"],
  "mail.changed": ["threads", "thread", "mail-status", "search", "documents", "panel-results", "today", "summary", "triage-estimate", "mail-folders"],
  "mail.syncChanged": ["mail-status", "connectors", "cockpit", "pipelines", "mail-folders"],
  "mail.syncProgress": ["mail-status", "jobs", "cockpit", "pipelines"],
  "mail.pulled": ["mail-status", "cockpit", "pipelines", "mail-folders"],
  "mail.historyFinished": ["mail-status", "cockpit", "pipelines", "mail-folders", "cockpit-events"],
  "pst.searchChanged": ["pst-search", "jobs", "cockpit"],
  "pst.uploadProgress": ["jobs", "cockpit"],
  "triggers.changed": ["triggers", "schedules"],
  "connectors.changed": ["connectors"],
  "mail.accountsChanged": ["mail-accounts", "mail-status", "threads", "connectors", "pipelines"],
  "thread.updated": ["threads", "thread", "mail-folders"],
  "drafts.changed": ["drafts"],
  "rules.changed": ["rules"],
  "documents.changed": ["documents", "document", "panel-results"],
  "document.indexed": ["documents", "document", "search"],
  "pst.progress": ["pst", "mail-status", "jobs"],
  "panels.changed": ["panels"],
  "session.changed": ["sessions", "session", "session-context", "jobs", "usage", "cockpit", "agent-queue"],
  "agent.triggered": ["sessions", "jobs", "cockpit"],
  "agent.held": ["jobs"],
  "mailAgent.changed": ["mail-agent", "schedules"],
  "context.changed": ["context"],
  "schedule.due": ["schedules", "agent-queue"],
  "queue.changed": ["agent-queue", "cockpit"],
  "channel.posted": ["channel", "today"],
  "board.changed": ["board", "today"],
  "tasks.changed": ["tasks", "today"],
  "reminders.changed": ["reminders", "today"],
  "schedule.changed": ["schedules"],
  "schedule.ran": ["schedules", "jobs"],
  "activity.added": ["activity"],
  "memory.changed": ["memory", "knowledge"],
  "suggestions.changed": ["suggestions", "today"],
  "prompts.changed": ["prompts", "prompt-history", "knowledge"],
  "preferences.changed": ["preferences", "preference-history", "knowledge", "today"],
  "brief.ready": ["today"],
  "agentChannel.posted": ["agent-channel"],
  "summary.ready": ["summary"],
  "mail.triaged": ["threads", "thread", "today", "runs", "jobs", "triage-estimate"],
  "approval.changed": ["approvals"],
  "permissions.changed": ["permissions"],
  "notifications.changed": ["notifications"],
};

const EVENT_RECONNECT_MS = 3000;

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
    // Native reconnect covers ordinary disconnects; a proxy HTTP error can close it permanently.
    let source: EventSource | null = null;
    let cancelled = false;
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    let seq: number | null = null;
    const retry = () => {
      if (cancelled) return;
      clearTimeout(reconnect);
      reconnect = setTimeout(() => void connect(), EVENT_RECONNECT_MS);
    };
    const connect = async () => {
      try {
        seq ??= await latestSeq();
        if (cancelled) return;
        source = new EventSource(`${EVENTS_URL}?since=${seq}`);
        source.onopen = () => {
          setConnected(true);
          // Anything could have changed before this connection opened.
          void refresh(client);
        };
        source.onerror = () => {
          setConnected(false);
          if (source?.readyState === EventSource.CLOSED) retry();
        };
        source.onmessage = (message) => {
          const event = JSON.parse(message.data as string) as AppEvent;
          seq = Math.max(seq ?? 0, event.seq);
          if (event.type === "generation.changed") {
            const state = event.payload as GenerationState;
            for (const key of [state.trace_id ? ["generation", "trace", state.trace_id] : null, state.session ? ["generation", "session", state.session] : null]) {
              if (!key) continue;
              // A snapshot taken before this event mustn't replace a newer phase when it arrives.
              void client.cancelQueries({ queryKey: key });
              client.setQueryData<GenerationState>(key, (previous) => (previous?.call_id ?? 0) > (state.call_id ?? 0) ? previous : state);
            }
          }
          // This event carries the new list and counts, so nothing has to go and ask.
          if (event.type === "semantic.changed") {
            void client.cancelQueries({ queryKey: ["semantic"] });
            client.setQueryData(["semantic"], event.payload);
            void refresh(client, { queryKey: ["jobs"] });
          }
          if (event.type === "categories.changed" && event.payload.categories) {
            void client.cancelQueries({ queryKey: ["categories"] });
            client.setQueryData(["categories"], { categories: event.payload.categories });
          }
          for (const key of INVALIDATES[event.type] ?? []) void refresh(client, { queryKey: [key] });
          for (const listener of listeners.current) listener(event);
        };
      } catch { setConnected(false); retry(); }
    };
    void connect();
    return () => {
      cancelled = true;
      clearTimeout(reconnect);
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
