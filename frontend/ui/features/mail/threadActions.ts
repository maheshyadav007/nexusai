"use client";

import { useRouter } from "next/navigation";
import type { ThreadRow } from "@/ui/client/contracts.generated";
import { useMoveThread, useSetFlag, useSetRead, useToInbox } from "@/ui/client/mail";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import type { MenuItem } from "@/ui/primitives/Menu";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";

/** What can be done to a conversation. The right-click menu and any toolbar read this one list. */
export function useThreadActions(thread: ThreadRow, href?: string): MenuItem[] {
  const router = useRouter();
  const setRead = useSetRead();
  const setFlag = useSetFlag();
  const move = useMoveThread();
  const toInbox = useToInbox();
  const toast = useToast();
  const assistant = useAssistant();
  const failed = (error: Error) => toast({ title: error.message, tone: "danger" });
  // Back where the person reads, and the AI with it. Always is offered after, for the sender.
  const backToInbox = () => toInbox.mutate({ id: thread.id }, {
    onError: failed,
    onSuccess: ({ sender }) => toast({ title: t("mail.toInbox.done"), ...(sender ? { action: { label: t("mail.toInbox.always", { sender }), run: () => toInbox.mutate({ id: thread.id, always: true }, { onError: failed, onSuccess: () => toast({ title: t("mail.toInbox.alwaysDone", { sender }) }) }) } } : {}) }),
  });
  const unread = thread.unread_count > 0;
  return [
    { id: "open", label: t("menu.open"), onSelect: () => router.push(href ?? `/mail/all/${thread.id}`) },
    { id: "read", label: t(unread ? "mail.markRead" : "mail.markUnread"), icon: "markUnread", onSelect: () => setRead.mutate({ id: thread.id, read: unread }) },
    { id: "flag", label: t(thread.flagged ? "mail.unflag" : "mail.flag"), icon: "starred", onSelect: () => setFlag.mutate({ id: thread.id, flagged: !thread.flagged }) },
    { id: "ask", label: t("menu.askAgent"), icon: "chat", onSelect: () => assistant.start({ context: [`thread:${thread.id}`], title: thread.subject || t("mail.noSubject") }) },
    ...(thread.category ? [{ id: "inbox", label: t("mail.toInbox"), icon: "inbox" as const, onSelect: backToInbox }] : []),
    { id: "archive", label: t("mail.archive"), icon: "archive", onSelect: () => move.mutate({ id: thread.id, to: "archive" }) },
    { id: "delete", label: t("mail.delete"), icon: "trash", danger: true, onSelect: () => move.mutate({ id: thread.id, to: "trash" }) },
  ];
}
