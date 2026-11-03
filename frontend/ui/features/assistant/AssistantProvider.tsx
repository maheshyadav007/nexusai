"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { createContext, use, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import appConfig from "@/app.config.json";
import type { CreateSession } from "@/ui/client/contracts.generated";
import { query } from "@/ui/client/api";
import { clearChatDraft, leaveFirstMessage, useCreateSession } from "@/ui/client/sessions";

interface Start {
  text?: string;
  context?: readonly string[];
  title?: string;
  model?: string | null;
  agent?: "session" | "interview";
}

// Reading an email makes room by minimizing the attached chat.
const READING = /^\/(mail\/.+|search)\/\d+$/;

interface Assistant {
  /** Whether it's on screen right now. */
  open: boolean;
  ready: boolean;
  /** Tucked away to the edge, ready to come out, because what's open needs the room. */
  tucked: boolean;
  /** Out from the edge for now, and goes back when the person's done. */
  peeking: boolean;
  /** A document in a large preview needs the room just as a conversation does. */
  setNeedsRoom: (needed: boolean) => void;
  /** Attached to the right edge, with the page beside it instead of under it. */
  pinned: boolean;
  returnTo: string;
  draftRevision: number;
  session: string | null;
  starting: boolean;
  startingTitle: string | null;
  startingText: string | null;
  startError: string | null;
  setOpen: (open: boolean) => void;
  setPinned: (pinned: boolean) => void;
  openSession: (id: string) => void;
  newChat: () => void;
  openDraft: () => void;
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
  const router = useRouter();
  const [wanted, setWanted] = useState(false);
  const [returnTo, setReturnTo] = useState("/today");
  const lastPath = useRef(pathname);
  const keepOpen = useRef(false);
  const open = wanted;
  const setOpen = useCallback((next: boolean) => setWanted(next), []);
  // Opening content makes room for reading. Explicitly docking from full page wins once.
  useEffect(() => {
    if (pathname.startsWith("/agent/sessions/")) return;
    setReturnTo(pathname);
    if (pathname !== lastPath.current && READING.test(pathname) && !keepOpen.current) setWanted(false);
    keepOpen.current = false;
    lastPath.current = pathname;
  }, [pathname]);
  const setNeedsRoom = useCallback((needed: boolean) => { if (needed) setWanted(false); }, []);
  // Floating view is disabled; the panel is always attached to the right edge.
  const pinned = true;
  const [draftRevision, setDraftRevision] = useState(0);
  const [session, setSession] = useState<string | null>(null);
  const create = useCreateSession();
  const { mutate } = create;
  const client = useQueryClient();
  const [starting, setStarting] = useState(false);
  const [startingTitle, setStartingTitle] = useState<string | null>(null);
  const [startingText, setStartingText] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const startLock = useRef(false);

  // Saving waits until it's been read, or the empty start would overwrite what was there.
  const [restored, setRestored] = useState(false);
  useEffect(() => {
    const saved = remembered();
    setWanted(saved.open && !READING.test(pathname));
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
    ({ text, context, title, model, agent }: Start) => {
      if (startLock.current) return;
      startLock.current = true;
      setStarting(true);
      setStartingTitle(title ?? null);
      setStartingText(text ?? null);
      setStartError(null);
      setSession(null);
      setOpen(true);
      const input = { ...(agent ? { agent } : {}), ...(context ? { context: context as CreateSession["context"] } : {}), ...(title ? { title } : {}), ...(model ? { model } : {}) };
      mutate(input, {
        // The shell is already visible; fill it once the session and its context are ready.
        onSuccess: (row) => {
          if (text) leaveFirstMessage(row.id, text);
          void Promise.allSettled([
            client.prefetchQuery({ queryKey: ["session", row.id], queryFn: () => query("session.get", { id: row.id }) }),
            client.prefetchQuery({ queryKey: ["session-context", row.id], queryFn: () => query("session.context", { id: row.id }) }),
          ]).then(() => {
            setSession(row.id);
            if (pathname.startsWith("/agent/sessions/")) {
              setOpen(false);
              router.replace(`/agent/sessions/${row.id}?view=full`);
            }
            setStarting(false);
            startLock.current = false;
          });
        },
        onError: (error) => {
          setStarting(false);
          startLock.current = false;
          setStartError(error.message);
        },
      });
    },
    [client, mutate, setOpen, pathname, router],
  );
  const value = useMemo<Assistant>(
    () => ({
      open,
      ready: restored,
      tucked: false,
      peeking: false,
      setNeedsRoom,
      pinned,
      returnTo,
      draftRevision,
      session,
      starting,
      startingTitle,
      startingText,
      startError,
      setOpen,
      setPinned: () => undefined,
      openSession: (id) => {
        if (pathname.startsWith("/agent/sessions/")) { keepOpen.current = true; router.push(returnTo); }
        setSession(id);
        setOpen(true);
      },
      openDraft: () => {
        if (pathname.startsWith("/agent/sessions/")) { keepOpen.current = true; router.push(returnTo); }
        setSession(null);
        setOpen(true);
      },
      newChat: () => {
        clearChatDraft("new");
        setDraftRevision((value) => value + 1);
        setSession(null);
        setStartError(null);
        setOpen(true);
      },
      start,
    }),
    [open, restored, setOpen, setNeedsRoom, pinned, returnTo, draftRevision, pathname, router, session, starting, startingTitle, startingText, startError, start],
  );
  return <AssistantContext value={value}>{children}</AssistantContext>;
}
