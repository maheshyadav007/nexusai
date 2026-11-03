"use client";

import { useRouter } from "next/navigation";
import { IconButton } from "@/ui/primitives/IconButton";
import { t } from "@/ui/strings";
import { useAssistant } from "./AssistantProvider";

/** The same view controls on the dock and full page; never starts another agent run. */
export function ChatViewActions({ session, full = false }: { session: string | null; full?: boolean }) {
  const assistant = useAssistant();
  const router = useRouter();
  const leave = (showPanel: boolean) => {
    if (session) assistant.openSession(session);
    else assistant.openDraft();
    assistant.setOpen(showPanel);
    router.push(assistant.returnTo);
  };
  return <div className="flex shrink-0 items-center gap-1">
    <IconButton icon="newChat" label={t("chat.new")} disabled={assistant.starting} onClick={() => { assistant.newChat(); if (full) router.push("/agent/sessions/new"); }} />
    {full ? <IconButton icon="pin" label={t("chat.dock")} onClick={() => leave(true)} /> : <IconButton icon="openFull" label={t("chat.expand")} disabled={assistant.starting} onClick={() => { assistant.setOpen(false); router.push(session ? `/agent/sessions/${session}` : "/agent/sessions/new"); }} />}
    <IconButton icon="minimize" label={t("chat.minimize")} onClick={() => full ? leave(false) : assistant.setOpen(false)} />
  </div>;
}
