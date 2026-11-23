"use client";

import type { MatterChange, MatterRow } from "@/ui/client/contracts.generated";
import { useMatterList, useMatterReopen, useMergeMatter, useUnlinkThread, useUnmergeMatter } from "@/ui/client/work";
import { useLeadName } from "@/ui/client/home";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { useHideFromAi } from "@/ui/features/mail/HideFromAi";
import { useOpenSource } from "@/ui/features/sources/context";
import type { MenuItem } from "@/ui/primitives/Menu";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";
import { changeSource, useMatterDoneWithUndo, useTodayView } from "./parts";

/** Its newest conversation, the one Ask and Hide from AI start from. */
const latestThread = (matter: MatterRow) => (matter.latest?.kind === "mail" ? Number(matter.latest.ref) : null);

/** What can be done to a matter, the same list wherever it's shown: its page, the list, a Brief
 *  row, a Week lane. Only Done is a button anywhere, on its page; the rest live here. */
export function useMatterActions(matter: MatterRow, { open = true, toStart }: { open?: boolean; toStart?: () => void } = {}): MenuItem[] {
  const { go } = useTodayView();
  const finish = useMatterDoneWithUndo();
  const reopen = useMatterReopen();
  const merge = useMergeMatter();
  const unmerge = useUnmergeMatter();
  const others = useMatterList(false).data?.matters.filter((other) => other.id !== matter.id) ?? [];
  const hide = useHideFromAi();
  const assistant = useAssistant();
  const toast = useToast();
  const lead = useLeadName();
  const thread = latestThread(matter);
  const into = (other: MatterRow) => merge.mutate({ id: other.id, into: matter.id }, {
    onSuccess: () => toast({ title: t("matters.related.merged"), action: { label: t("matters.unmerge"), run: () => unmerge.mutate(other.id) } }),
    onError: (error) => toast({ title: error.message, tone: "danger" }),
  });
  return [
    ...(open ? [{ id: "open", label: t("menu.open"), onSelect: () => go("matters", matter.id) }] : []),
    matter.state === "done"
      ? { id: "reopen", label: t("matters.menu.reopen"), onSelect: () => reopen.mutate(matter.id) }
      : { id: "done", label: t("matters.done"), icon: "check" as const, onSelect: () => finish(matter) },
    { id: "merge", label: t("matters.menu.merge"), items: others.slice(0, 12).map((other) => ({ id: `merge-${other.id}`, label: other.title, onSelect: () => into(other) })) },
    ...(toStart ? [{ id: "start", label: t("matters.menu.toStart"), icon: "moveUp" as const, onSelect: toStart }] : []),
    ...(thread ? [
      { id: "ask", label: t("matters.menu.ask", { name: lead }), icon: "chat" as const, divider: true, onSelect: () => assistant.start({ context: [`thread:${thread}`], title: matter.title }) },
      { id: "hide", label: t("menu.hideFromAi"), icon: "keptFromAi" as const, onSelect: () => hide(thread) },
    ] : []),
  ];
}

/** What can be done to one email on a matter's timeline. */
export function useTimelineActions(change: MatterChange, { toStart }: { toStart: () => void }): MenuItem[] {
  const source = changeSource(change);
  const openSource = useOpenSource();
  const unlink = useUnlinkThread();
  const hide = useHideFromAi();
  const toast = useToast();
  const thread = source?.kind === "mail" ? Number(source.ref) : null;
  return [
    ...(source ? [{ id: "open", label: t("matters.menu.openEmail"), onSelect: () => openSource.open(source) }] : []),
    { id: "start", label: t("matters.menu.toStart"), icon: "moveUp" as const, onSelect: toStart },
    ...(thread ? [
      { id: "unlink", label: t("matters.menu.notPart"), divider: true, onSelect: () => unlink.mutate(thread, { onSuccess: () => toast({ title: t("matters.notPart.done") }) }) },
      { id: "hide", label: t("menu.hideFromAi"), icon: "keptFromAi" as const, onSelect: () => hide(thread) },
    ] : []),
  ];
}
