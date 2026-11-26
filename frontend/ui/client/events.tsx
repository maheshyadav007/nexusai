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
  "models.changed": ["models", "models-available", "cockpit"],
  "onboarding.changed": ["onboarding"],
  "profile.changed": ["profile"],
  "sidebar.changed": ["sidebar"],
  "mail.changed": ["threads", "thread", "mail-status", "search", "documents", "panel-results", "today", "summary", "triage-estimate", "mail-folders", "matters"],
  "mail.syncChanged": ["mail-status", "connectors", "cockpit", "pipelines", "mail-folders"],
  "mail.syncProgress": ["mail-status", "jobs", "cockpit", "pipelines"],
  "mail.pulled": ["mail-status", "cockpit", "pipelines", "mail-folders"],
  "mail.historyFinished": ["mail-status", "mail-sort", "cockpit", "pipelines", "mail-folders", "cockpit-events"],
  "mail.sortChanged": ["mail-sort"],
  "mail.sorted": ["mail-sort", "categories", "mail-organization"],
  "pst.searchChanged": ["pst-search", "jobs", "cockpit"],
  "pst.uploadProgress": ["jobs", "cockpit"],
  "triggers.changed": ["triggers", "schedules", "routine-runs"],
  "connectors.changed": ["connectors"],
  "mail.accountsChanged": ["mail-accounts", "mail-status", "threads", "connectors", "pipelines"],
  "thread.updated": ["threads", "thread", "mail-folders"],
  "drafts.changed": ["drafts"],
  "rules.changed": ["rules", "mixed-folders", "rule-preview"],
  "categories.changed": ["mixed-folders", "mail-folders"],
  "documents.changed": ["documents", "document", "panel-results"],
  "document.indexed": ["documents", "document", "search"],
  "pst.progress": ["pst", "mail-status", "jobs"],
  "panels.changed": ["panels"],
  "session.changed": ["sessions", "session", "session-context", "jobs", "usage", "cockpit", "agent-queue", "agent-cards", "agent-map", "runs", "run-tree", "routine-runs"],
  "agent.triggered": ["sessions", "jobs", "cockpit"],
  "agent.held": ["jobs"],
  "mailAgent.changed": ["mail-agent", "schedules"],
  "context.changed": ["context"],
  "schedule.due": ["schedules", "agent-queue"],
  "queue.changed": ["agent-queue", "cockpit"],
  "channel.posted": ["channel", "today"],
  "tasks.changed": ["tasks", "today", "matters"],
  "reminders.changed": ["reminders", "today", "matters"],
  "schedule.changed": ["schedules", "routine-runs"],
  "checks.changed": ["checks"],
  "schedule.ran": ["schedules", "jobs"],
  "activity.added": ["activity"],
  "memory.changed": ["memory", "knowledge"],
  "suggestions.changed": ["suggestions", "today"],
  "prompts.changed": ["prompts", "prompt-history", "knowledge"],
  "preferences.changed": ["preferences", "preference-history", "knowledge", "today"],
  "brief.ready": ["today"],
  "matters.changed": ["matters"],
  "agentChannel.posted": ["agent-channel"],
  "skills.changed": ["skills"],
  "monitor.alerted": ["agent-map", "notifications"],
  "team.changed": ["team-tasks", "team-task", "agent-cards", "agent-channel", "agent-map", "runs", "run-tree"],
  "agents.changed": ["agent-cards", "sessions", "session", "agents", "schedules", "triggers", "prompts", "home"],
  "summary.ready": ["summary"],
  "mail.triaged": ["threads", "thread", "today", "matters", "runs", "jobs", "triage-estimate"],
  "approval.changed": ["approvals"],
  "permissions.changed": ["permissions"],
  "notifications.changed": ["notifications"],
};

const EVENT_RECONNECT_MS = 3000;
// Events come in bursts while mail downloads. What they make stale is read again once per
// burst, a moment after it, and at least this often while it lasts, so a slow list isn't
// cancelled by each new event before it can arrive.
const EVENT_SETTLE_MS = 250;
const EVENT_MAX_WAIT_MS = 1500;

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
    const stale = new Set<string>();
    let settle: ReturnType<typeof setTimeout> | undefined;
    let since = 0;
    const flush = () => {
      clearTimeout(settle);
      settle = undefined;
      since = 0;
      const keys = [...stale];
      stale.clear();
      for (const key of keys) void refresh(client, { queryKey: [key] });
    };
    const later = (keys: readonly string[]) => {
      if (!keys.length) return;
      for (const key of keys) stale.add(key);
      since ||= Date.now();
      clearTimeout(settle);
      settle = setTimeout(flush, Date.now() - since >= EVENT_MAX_WAIT_MS ? 0 : EVENT_SETTLE_MS);
    };
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
            later(["jobs"]);
          }
          if (event.type === "categories.changed" && event.payload.categories) {
            void client.cancelQueries({ queryKey: ["categories"] });
            client.setQueryData(["categories"], { categories: event.payload.categories });
          }
          later(INVALIDATES[event.type] ?? []);
          for (const listener of listeners.current) listener(event);
        };
      } catch { setConnected(false); retry(); }
    };
    void connect();
    return () => {
      cancelled = true;
      clearTimeout(reconnect);
      clearTimeout(settle);
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
