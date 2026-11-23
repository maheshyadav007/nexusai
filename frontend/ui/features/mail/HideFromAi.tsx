"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useState, type ReactNode } from "react";
import { command, query } from "@/ui/client/api";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { ChoiceCards } from "@/ui/primitives/TileGroup";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";

type Scope = "sender" | "conversation";
// Everything the app shows that hiding changes, refreshed after it and after its Undo.
const CHANGED = ["threads", "thread", "categories", "mail-folders", "rules", "tasks", "reminders", "matters", "today"];

const HideContext = createContext<(thread: number) => void>(() => undefined);

/** Opens "Hide from AI" for a conversation, from an email, a matter or the week. */
export const useHideFromAi = () => useContext(HideContext);

/** One place the dialog lives, so every screen that offers Hide from AI opens the same one. */
export function HideFromAiProvider({ children }: { children: ReactNode }) {
  const [thread, setThread] = useState<number | null>(null);
  return (
    <HideContext.Provider value={setThread}>
      {children}
      {thread !== null ? <HideDialog thread={thread} onClose={() => setThread(null)} /> : null}
    </HideContext.Provider>
  );
}

/** Asks once, everything from the sender or just this conversation, and says what will happen
 *  before it does. Done, it offers one Undo for all of it. */
function HideDialog({ thread, onClose }: { thread: number; onClose: () => void }) {
  const client = useQueryClient();
  const toast = useToast();
  const preview = useQuery({ queryKey: ["hide-preview", thread], queryFn: () => query("mail.hide.preview", { thread }) });
  const [scope, setScope] = useState<Scope>("sender");
  const refresh = () => Promise.all(CHANGED.map((key) => client.invalidateQueries({ queryKey: [key] })));
  const undo = useMutation({ mutationFn: (id: number) => command("mail.hide.undo", { undo: id }), onSettled: refresh });
  const hide = useMutation({
    mutationFn: () => command("mail.hide", { thread, scope: preview.data?.sender ? scope : "conversation" }),
    onSuccess: (done) => {
      void refresh();
      onClose();
      const name = preview.data?.sender && scope === "sender" ? preview.data.sender_name ?? "" : t("hide.thisConversation");
      toast({ title: t("hide.done", { name }), action: { label: t("hide.undo"), run: () => undo.mutate(done.undo, { onError: (error) => toast({ title: error.message, tone: "danger" }) }) } });
    },
  });
  const seen = preview.data;
  const bySender = Boolean(seen?.sender) && scope === "sender";
  const point = (icon: "keptFromAi" | "forward" | "check" | "info", text: string, quiet = false) => (
    <li className={`flex items-center gap-3 text-md ${quiet ? "text-ink-muted" : "text-ink-secondary"}`}><Icon name={icon} className="h-4 w-4 shrink-0 text-ink-muted" />{text}</li>
  );
  return (
    <Dialog title={t("hide.title")} open onOpenChange={(open) => { if (!open) onClose(); }}>
      {!seen ? <Skeleton className="h-6 w-full" /> : (
        <div data-testid="hide-from-ai" className="flex flex-col gap-4">
          {seen.sender ? (
            <div className="flex flex-col gap-2">
              <p className="text-md text-ink-secondary">{t("hide.question")}</p>
              <ChoiceCards label={t("hide.question")} value={scope} onChange={setScope} choices={[
                { value: "sender", label: t("hide.sender", { name: seen.sender_name ?? "" }), description: t("hide.sender.about") },
                { value: "conversation", label: t("hide.conversation"), description: t("hide.conversation.about") },
              ]} />
            </div>
          ) : null}
          <ul className="flex flex-col gap-2">
            {point("keptFromAi", bySender ? t("hide.moves.sender", { count: (seen.sender_emails ?? 0).toLocaleString(), folder: seen.folder ?? "" }) : t("hide.moves.conversation", { count: (seen.conversation_emails ?? 0).toLocaleString() }))}
            {bySender ? point("forward", t("hide.next", { name: seen.sender_name ?? "" })) : null}
            {point("check", t("hide.work"))}
            {point("info", t("hide.server"), true)}
          </ul>
          {hide.isError ? <p role="alert" className="text-sm text-status-danger">{hide.error.message}</p> : null}
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>{t("hide.cancel")}</Button>
            <Button variant="primary" loading={hide.isPending} onClick={() => hide.mutate()}>{t("hide.title")}</Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
