"use client";

import { AnimatePresence, motion } from "motion/react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useEvents } from "@/ui/client/events";
import { groupApprovals, useApprovals, useSessions } from "@/ui/client/sessions";
import { useChannel } from "@/ui/client/work";
import { Icon, type IconName } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { FADE_RISE } from "@/ui/primitives/motion";
import { t, tn } from "@/ui/strings";
import { useAssistant } from "./AssistantProvider";

interface Note {
  key: string;
  icon: IconName;
  title: string;
  detail: string;
  action?: { label: string; run: () => void };
  /** Stays until it's dealt with, because something is waiting on it. */
  sticky: boolean;
}

const MOST_SHOWN = 3;
const SHOWN_MS = 8000;
// Their own screen already shows these.
const NOT_ON = ["/today"];

/** What the agents need or want to say, in a small rounded card at the bottom right. */
export function AgentToasts() {
  const [notes, setNotes] = useState<readonly Note[]>([]);
  const assistant = useAssistant();
  const router = useRouter();
  const pathname = usePathname();
  const channel = useChannel();
  const approvals = useApprovals();
  const sessions = useSessions("");
  const { subscribe } = useEvents();
  // Everything already there when the app opened isn't news.
  const seen = useRef<Set<string> | null>(null);

  const push = (note: Note) => {
    setNotes((current) => (current.some((item) => item.key === note.key) ? current : [...current, note].slice(-MOST_SHOWN)));
    if (!note.sticky) setTimeout(() => setNotes((current) => current.filter((item) => item.key !== note.key)), SHOWN_MS);
  };

  useEffect(() => {
    if (!channel.data || !approvals.data) return;
    const asks = channel.data.messages.filter((message) => message.kind === "ask");
    const pending = approvals.data.approvals;
    const groups = groupApprovals(pending);
    const groupKey = (item: { session: string; tool: string }) => `approval-${item.session}-${item.tool}`;
    const live = new Set([...asks.map((item) => `ask-${item.id}`), ...pending.map(groupKey)]);
    if (seen.current === null) {
      seen.current = live;
      return;
    }
    const watched = assistant.open ? assistant.session : null;
    for (const item of asks) {
      const key = `ask-${item.id}`;
      if (seen.current.has(key) || item.session === watched || NOT_ON.includes(pathname) || pathname === `/agent/sessions/${item.session}`) continue;
      const session = item.session;
      push({ key, icon: "chat", title: sessions.data?.sessions.find((row) => row.id === session)?.title ?? item.agent, detail: item.text, sticky: true, action: { label: t("toast.answer"), run: () => (session && session !== "mail-agent" ? assistant.openSession(session) : router.push("/today")) } });
    }
    for (const group of groups) {
      const item = group[0];
      if (!item) continue;
      const key = groupKey(item);
      if (seen.current.has(key) || item.session === watched || NOT_ON.includes(pathname) || pathname === `/agent/sessions/${item.session}`) continue;
      const session = item.session;
      push({ key, icon: "approvals", title: t("toast.approval"), detail: group.length > 1 ? tn("approvals.group", group.length, { label: item.tool_label ?? item.tool }) : item.summary, sticky: true, action: { label: t("toast.review"), run: () => assistant.openSession(session) } });
    }
    seen.current = new Set([...seen.current, ...live]);
    // Anything answered elsewhere goes away by itself.
    setNotes((current) => current.filter((note) => !note.sticky || live.has(note.key)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs when what's waiting changes
  }, [channel.data, approvals.data]);

  useEffect(
    () =>
      subscribe((event) => {
        if (event.type !== "notification.requested" || event.payload.kind === "ask") return;
        const { title, detail, link } = event.payload as { title?: string; detail?: string; link?: string };
        push({
          key: `note-${event.seq}`,
          icon: "notifications",
          title: title ?? t("app.name"),
          detail: detail ?? "",
          sticky: false,
          ...(link ? { action: { label: t("toast.open"), run: () => router.push(link) } } : {}),
        });
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- push only touches state
    [subscribe, router],
  );

  const dismiss = (key: string) => setNotes((current) => current.filter((item) => item.key !== key));
  return (
    <div role="region" aria-label={t("toast.region")} className={`pointer-events-none fixed z-50 flex w-popover max-w-full flex-col gap-2 ${assistant.open ? "bottom-4 right-dock" : "bottom-7 right-4 pb-3"}`}>
      <AnimatePresence initial={false}>
        {notes.map((note) => (
          <motion.div key={note.key} layout {...FADE_RISE} data-testid="agent-toast" className="pointer-events-auto mr-4 flex items-start gap-3 rounded-lg border border-line-subtle bg-surface-raised p-3 shadow-overlay">
            <Icon name={note.icon} className="mt-px h-4 w-4 shrink-0 text-ink-secondary" />
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <p className="truncate text-md font-medium text-ink-primary">{note.title}</p>
              {note.detail ? <p className="line-clamp-3 break-words text-md text-ink-secondary">{note.detail}</p> : null}
              {note.action ? (
                <div className="mt-1">
                  <Button
                    onClick={() => {
                      note.action?.run();
                      dismiss(note.key);
                    }}
                  >
                    {note.action.label}
                  </Button>
                </div>
              ) : null}
            </div>
            <button type="button" aria-label={t("toast.dismiss")} onClick={() => dismiss(note.key)} className="focus-ring rounded-sm p-px text-ink-muted transition-colors duration-fast hover:text-ink-primary">
              <Icon name="close" className="h-3 w-3" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
