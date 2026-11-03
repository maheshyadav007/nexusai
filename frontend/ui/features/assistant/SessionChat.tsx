"use client";

import type { UIMessage } from "ai";
import { useEffect, useState, type ReactNode } from "react";
import { isManagedSession, useSession } from "@/ui/client/sessions";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";
import { Button } from "@/ui/primitives/Button";
import { useAssistant } from "./AssistantProvider";
import { usePathname, useRouter } from "next/navigation";
import { ChatView } from "./ChatView";

/** Loads a session once. After that the live conversation belongs to useChat. */
export function SessionChat({ id, footer }: { id: string; footer?: ReactNode }) {
  const session = useSession(id);
  const assistant = useAssistant();
  const router = useRouter();
  const pathname = usePathname();
  const [start, setStart] = useState<{ messages: UIMessage[]; active: boolean } | null>(null);
  useEffect(() => {
    if (session.data && !start) setStart({ messages: session.data.messages as unknown as UIMessage[], active: session.data.active });
  }, [session.data, start]);
  if (session.isError) return <div className="p-4"><ErrorState title={t("sessions.error")} description={session.error.message} /></div>;
  if (!session.data || !start) return <div aria-busy className="p-4"><Skeleton className="h-6 w-full" /></div>;
  const row = session.data.session;
  return <>
    {isManagedSession(row) ? <aside data-testid="managed-chat-notice" className="flex shrink-0 flex-col gap-1 border-y border-line-subtle bg-surface-sunken/40 px-4 py-3">
      <p className="text-sm font-medium text-ink-primary">{t(row.agent === "interview" ? "chat.guided.title" : "chat.managed.title")}</p>
      <p className="text-sm text-ink-muted">{t(row.agent === "interview" ? "chat.guided.hint" : "chat.managed.hint")}</p>
      <div><Button variant="quiet" onClick={() => { assistant.newChat(); if (pathname.startsWith("/agent/sessions/")) router.push("/agent/sessions/new"); }}>{t("chat.managed.new")}</Button></div>
    </aside> : null}
    <ChatView key={id} id={id} initial={start.messages} active={start.active} footer={footer} />
  </>;
}
