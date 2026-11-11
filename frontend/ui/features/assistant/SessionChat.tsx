"use client";

import type { UIMessage } from "ai";
import { useEffect, useState, type ReactNode } from "react";
import { useSession } from "@/ui/client/sessions";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";
import { ChatView } from "./ChatView";

/** Loads a session once. After that the live conversation belongs to useChat. */
export function SessionChat({ id, footer }: { id: string; footer?: ReactNode }) {
  const session = useSession(id);
  const [start, setStart] = useState<{ messages: UIMessage[]; active: boolean } | null>(null);
  // Reopening a minimized chat finds the copy cached before it closed, missing the steps and any
  // run still going since, so it starts from a fresh one.
  const fresh = session.isFetchedAfterMount;
  useEffect(() => {
    if (session.data && fresh && !start) setStart({ messages: session.data.messages as unknown as UIMessage[], active: session.data.active });
  }, [session.data, fresh, start]);
  if (session.isError) return <div className="p-4"><ErrorState title={t("sessions.error")} description={session.error.message} /></div>;
  if (!session.data || !start) return <div aria-busy className="p-4"><Skeleton className="h-6 w-full" /></div>;
  return <ChatView key={id} id={id} initial={start.messages} active={start.active} footer={footer} />;
}
