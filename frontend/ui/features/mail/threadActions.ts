"use client";

import { useRouter } from "next/navigation";
import type { ThreadRow } from "@/ui/client/contracts.generated";
import { useMoveThread, useSetFlag, useSetRead } from "@/ui/client/mail";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import type { MenuItem } from "@/ui/primitives/Menu";
import { t } from "@/ui/strings";

/** What can be done to a conversation. The right-click menu and any toolbar read this one list. */
export function useThreadActions(thread: ThreadRow, href?: string): MenuItem[] {
  const router = useRouter();
  const setRead = useSetRead();
  const setFlag = useSetFlag();
  const move = useMoveThread();
  const assistant = useAssistant();
  const unread = thread.unread_count > 0;
  return [
    { id: "open", label: t("menu.open"), onSelect: () => router.push(href ?? `/mail/all/${thread.id}`) },
    { id: "read", label: t(unread ? "mail.markRead" : "mail.markUnread"), icon: "markUnread", onSelect: () => setRead.mutate({ id: thread.id, read: unread }) },
    { id: "flag", label: t(thread.flagged ? "mail.unflag" : "mail.flag"), icon: "starred", onSelect: () => setFlag.mutate({ id: thread.id, flagged: !thread.flagged }) },
    { id: "ask", label: t("menu.askAgent"), icon: "chat", onSelect: () => assistant.start({ context: [`thread:${thread.id}`], title: thread.subject || t("mail.noSubject") }) },
    { id: "archive", label: t("mail.archive"), icon: "archive", onSelect: () => move.mutate({ id: thread.id, to: "archive" }) },
    { id: "delete", label: t("mail.delete"), icon: "trash", danger: true, onSelect: () => move.mutate({ id: thread.id, to: "trash" }) },
  ];
}
