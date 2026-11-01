"use client";

import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import light from "@/ui/theme/themes/nexus-light.json";
import { useSessions } from "@/ui/client/sessions";
import { useWaitingCount } from "@/ui/client/work";
import { Icon } from "@/ui/icons";
import { IconButton } from "@/ui/primitives/IconButton";
import { QUICK, readSpace, SMOOTH } from "@/ui/primitives/motion";
import { Select } from "@/ui/primitives/Select";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { Tooltip } from "@/ui/primitives/Tooltip";
import { t, tn } from "@/ui/strings";
import { useAssistant } from "./AssistantProvider";
import { Composer } from "./Composer";
import { SessionChat } from "./SessionChat";

const STARTERS = ["chat.starter.today", "chat.starter.mail", "chat.starter.reminder"] as const;
const SELF_RUNNING = "mail";

function NewChat() {
  const assistant = useAssistant();
  const [text, setText] = useState("");
  const send = (words: string) => {
    if (words.trim()) assistant.start({ text: words.trim(), title: words.trim().slice(0, TITLE_LENGTH) });
  };
  return (
    <div className="flex min-h-0 flex-1 flex-col justify-end gap-3 p-3">
      <div className="flex flex-col px-1">
        <p className="mb-2 text-lg font-medium text-ink-primary">{t("chat.new.title")}</p>
        <ul className="flex flex-col border-t border-line-subtle">
          {STARTERS.map((key) => (
            <li key={key} className="border-b border-line-subtle">
              <button type="button" onClick={() => send(t(key))} className="focus-ring flex w-full items-center gap-2 py-2 text-left text-md text-ink-secondary transition-colors duration-fast hover:text-ink-primary">
                <Icon name="followUp" className="h-3 w-3 shrink-0 text-ink-muted" />
                {t(key)}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <Composer value={text} onChange={setText} onSubmit={() => send(text)} placeholder={t("sessions.prompt.placeholder")} label={t("sessions.prompt")} busy={assistant.starting} autoFocus />
    </div>
  );
}

const TITLE_LENGTH = 60;

const GAP = readSpace(light.space["4"]);
const FLOATING_HEIGHT = readSpace(light.layout.dockHeight);
const SMALL_SCREEN = readSpace(light.layout.page);

function useWindowSize() {
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const measure = () => setSize({ width: window.innerWidth, height: window.innerHeight });
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  return size;
}

function Panel() {
  const assistant = useAssistant();
  const sessions = useSessions("");
  const { width, height } = useWindowSize();
  const chats = (sessions.data?.sessions ?? []).filter((row) => row.agent !== SELF_RUNNING);
  const options = chats.map((row) => ({ value: row.id, label: row.status === "waiting" ? t("chat.waitingLabel", { title: row.title }) : row.title }));
  // Only one panel ever exists, so pinning moves it instead of restarting the conversation.
  const attached = assistant.pinned && width >= SMALL_SCREEN;
  const place = attached ? { top: 0, right: 0, bottom: 0, borderRadius: 0 } : { top: Math.max(GAP, height - GAP - FLOATING_HEIGHT), right: GAP, bottom: GAP, borderRadius: GAP - 2 };
  return (
    <motion.section
      initial={{ opacity: 0, x: attached ? 32 : 0, y: attached ? 0 : 12, ...place }}
      animate={{ opacity: 1, x: 0, y: 0, ...place }}
      exit={{ opacity: 0, x: attached ? 32 : 0, y: attached ? 0 : 12 }}
      transition={SMOOTH}
      aria-label={t("chat.title")}
      data-testid="assistant-dock"
      data-pinned={attached}
      className={`fixed z-40 flex w-dock max-w-full flex-col overflow-hidden border border-line-subtle bg-surface-page ${attached ? "border-y-0 border-r-0" : "shadow-overlay"}`}
    >
      <header className="flex min-h-topbar items-center gap-1 border-b border-line-subtle px-2">
        <div className="min-w-0 flex-1">
          {assistant.session && options.length ? <Select quiet label={t("chat.switch")} value={assistant.session} options={options} onChange={assistant.openSession} /> : <p className="px-2 text-md font-medium text-ink-primary">{t("chat.title")}</p>}
        </div>
        <IconButton icon="newChat" label={t("chat.new")} onClick={assistant.newChat} />
        {assistant.session ? (
          <Tooltip content={t("chat.expand")}>
            <Link href={`/agent/sessions/${assistant.session}`} aria-label={t("chat.expand")} className="focus-ring inline-flex rounded-md p-2 text-ink-secondary transition-colors duration-fast hover:bg-surface-sunken hover:text-ink-primary">
              <Icon name="openFull" />
            </Link>
          </Tooltip>
        ) : null}
        <IconButton icon={assistant.pinned ? "unpin" : "pin"} label={t(assistant.pinned ? "chat.unpin" : "chat.pin")} aria-pressed={assistant.pinned} onClick={() => assistant.setPinned(!assistant.pinned)} />
        <IconButton icon="minimize" label={t("chat.minimize")} onClick={() => assistant.setOpen(false)} />
      </header>
      {assistant.session ? <SessionChat key={assistant.session} id={assistant.session} /> : <NewChat />}
    </motion.section>
  );
}

/** Makes room beside the page for the pinned chat, moving with it as it slides in. */
export function AssistantRoom() {
  const assistant = useAssistant();
  const pathname = usePathname();
  const { width } = useWindowSize();
  const showing = assistant.open && assistant.pinned && width >= SMALL_SCREEN && !pathname.startsWith("/agent/sessions/");
  return <motion.div aria-hidden initial={false} animate={{ width: showing ? readSpace(light.layout.dock) : 0 }} transition={SMOOTH} className="shrink-0" />;
}

/** The chat, from anywhere in the app. It tucks into a small pill when it isn't needed. */
export function AssistantDock() {
  const assistant = useAssistant();
  const pathname = usePathname();
  const sessions = useSessions("");
  const waiting = useWaitingCount();
  const running = sessions.data?.running ?? 0;
  // The session page already is this conversation, and two live views of one chat would fight.
  if (pathname.startsWith("/agent/sessions/")) return null;
  return (
    <AnimatePresence initial={false}>
      {assistant.open ? (
        <Panel key="panel" />
      ) : (
        <motion.button key="pill" type="button" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }} transition={QUICK} onClick={() => assistant.setOpen(true)} data-testid="assistant-pill" className="focus-ring fixed bottom-4 right-4 z-40 flex items-center gap-2 rounded-full border border-line-subtle bg-surface-raised px-4 py-2 text-md font-medium text-ink-primary shadow-overlay transition-colors duration-fast hover:bg-surface-sunken">
          <Icon name="chat" />
          {t("chat.pill")}
          {waiting ? (
            <span className="flex items-center gap-1 text-sm tabular-nums text-accent-default">
              <StatusDot tone="waiting" />
              {tn("chat.waitingCount", waiting)}
            </span>
          ) : running ? (
            <StatusDot tone="running" />
          ) : null}
        </motion.button>
      )}
    </AnimatePresence>
  );
}
