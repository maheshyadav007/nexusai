"use client";

import { createContext, use, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import appConfig from "@/app.config.json";
import type { CreateSession } from "@/ui/client/contracts.generated";
import { leaveFirstMessage, useCreateSession } from "@/ui/client/sessions";

interface Start {
  text?: string;
  context?: readonly string[];
  title?: string;
}

interface Assistant {
  open: boolean;
  /** Attached to the right edge, with the page beside it instead of under it. */
  pinned: boolean;
  session: string | null;
  starting: boolean;
  setOpen: (open: boolean) => void;
  setPinned: (pinned: boolean) => void;
  openSession: (id: string) => void;
  newChat: () => void;
  start: (input: Start) => void;
}

const AssistantContext = createContext<Assistant | null>(null);

export function useAssistant(): Assistant {
  const value = use(AssistantContext);
  if (!value) throw new Error("useAssistant needs an AssistantProvider above it");
  return value;
}

// Only remembers where the person left off in this browser. It's fine if it comes back empty.
function remembered(): { open: boolean; pinned: boolean; session: string | null } {
  const fresh = { open: false, pinned: false, session: null };
  try {
    return { ...fresh, ...JSON.parse(localStorage.getItem(appConfig.storageKeys.assistant) ?? "{}") };
  } catch {
    return fresh;
  }
}

export function AssistantProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [session, setSession] = useState<string | null>(null);
  const create = useCreateSession();
  const { mutate } = create;

  // Saving waits until it's been read, or the empty start would overwrite what was there.
  const [restored, setRestored] = useState(false);
  useEffect(() => {
    const saved = remembered();
    setOpen(saved.open);
    setPinned(saved.pinned);
    setSession(saved.session);
    setRestored(true);
  }, []);
  useEffect(() => {
    if (!restored) return;
    try {
      localStorage.setItem(appConfig.storageKeys.assistant, JSON.stringify({ open, pinned, session }));
    } catch {
      // A blocked store only means it opens fresh next time.
    }
  }, [open, pinned, session, restored]);

  const start = useCallback(
    ({ text, context, title }: Start) => {
      setOpen(true);
      const input = { ...(context ? { context: context as CreateSession["context"] } : {}), ...(title ? { title } : {}) };
      mutate(input, {
        onSuccess: (row) => {
          if (text) leaveFirstMessage(row.id, text);
          setSession(row.id);
        },
      });
    },
    [mutate],
  );
  const value = useMemo<Assistant>(
    () => ({
      open,
      pinned,
      session,
      starting: create.isPending,
      setOpen,
      setPinned,
      openSession: (id) => {
        setSession(id);
        setOpen(true);
      },
      newChat: () => {
        setSession(null);
        setOpen(true);
      },
      start,
    }),
    [open, pinned, session, create.isPending, start],
  );
  return <AssistantContext value={value}>{children}</AssistantContext>;
}
