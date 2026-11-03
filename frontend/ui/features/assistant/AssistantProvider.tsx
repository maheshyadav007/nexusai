"use client";

import { usePathname } from "next/navigation";
import { createContext, use, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import appConfig from "@/app.config.json";
import type { CreateSession } from "@/ui/client/contracts.generated";
import { leaveFirstMessage, useCreateSession } from "@/ui/client/sessions";

interface Start {
  text?: string;
  context?: readonly string[];
  title?: string;
  model?: string | null;
}

// An open conversation or document needs the room, so an unpinned chat tucks away for it.
const READING = /^\/(mail\/.+|search)\/\d+$/;

interface Assistant {
  /** Whether it's on screen right now. */
  open: boolean;
  /** Tucked away to the edge, ready to come out, because what's open needs the room. */
  tucked: boolean;
  /** Out from the edge for now, and goes back when the person's done. */
  peeking: boolean;
  /** A document in a large preview needs the room just as a conversation does. */
  setNeedsRoom: (needed: boolean) => void;
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
  const pathname = usePathname();
  // What the person left it as. Tucking away is on top of this, so it comes back as it was.
  const [wanted, setWanted] = useState(false);
  const [peeking, setPeeking] = useState(false);
  const [needsRoom, setNeedsRoom] = useState(false);
  const [pinned, setPinned] = useState(false);
  const makingRoom = !pinned && (needsRoom || READING.test(pathname));
  const open = makingRoom ? peeking : wanted;
  const setOpen = useCallback((next: boolean) => (makingRoom ? setPeeking(next) : setWanted(next)), [makingRoom]);
  useEffect(() => {
    if (!makingRoom) setPeeking(false);
  }, [makingRoom]);
  const [session, setSession] = useState<string | null>(null);
  const create = useCreateSession();
  const { mutate } = create;

  // Saving waits until it's been read, or the empty start would overwrite what was there.
  const [restored, setRestored] = useState(false);
  useEffect(() => {
    const saved = remembered();
    setWanted(saved.open);
    setPinned(saved.pinned);
    setSession(saved.session);
    setRestored(true);
  }, []);
  useEffect(() => {
    if (!restored) return;
    try {
      localStorage.setItem(appConfig.storageKeys.assistant, JSON.stringify({ open: wanted, pinned, session }));
    } catch {
      // A blocked store only means it opens fresh next time.
    }
  }, [wanted, pinned, session, restored]);

  const start = useCallback(
    ({ text, context, title, model }: Start) => {
      setOpen(true);
      const input = { ...(context ? { context: context as CreateSession["context"] } : {}), ...(title ? { title } : {}), ...(model ? { model } : {}) };
      mutate(input, {
        onSuccess: (row) => {
          if (text) leaveFirstMessage(row.id, text);
          setSession(row.id);
        },
      });
    },
    [mutate, setOpen],
  );
  const value = useMemo<Assistant>(
    () => ({
      open,
      tucked: makingRoom && !peeking,
      peeking: makingRoom && peeking,
      setNeedsRoom,
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
    [open, makingRoom, peeking, setOpen, pinned, session, create.isPending, start],
  );
  return <AssistantContext value={value}>{children}</AssistantContext>;
}
