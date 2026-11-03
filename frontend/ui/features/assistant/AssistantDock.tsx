"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import light from "@/ui/theme/themes/nexus-light.json";
import { useSessions } from "@/ui/client/sessions";
import { useWaitingCount } from "@/ui/client/work";
import { Icon } from "@/ui/icons";
import { IconButton } from "@/ui/primitives/IconButton";
import { Presence, readSpace, RiseButton, Room, SlidePanel, Swap } from "@/ui/primitives/Motion";
import { Pressable } from "@/ui/primitives/Pressable";
import { Select } from "@/ui/primitives/Select";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { Tooltip } from "@/ui/primitives/Tooltip";
import { t, tn } from "@/ui/strings";
import { useAssistant } from "./AssistantProvider";
import { AttachedChips, AttachMenu, ModelPicker, useAttachedReading, type Attached } from "./ChatControls";
import { CompactAction } from "./ChatView";
import { Composer } from "./Composer";
import { SessionChat } from "./SessionChat";

const STARTERS = ["chat.starter.today", "chat.starter.mail", "chat.starter.reminder"] as const;
const MAIL_AGENT = "mail-agent";

function NewChat() {
  const assistant = useAssistant();
  const [text, setText] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [attached, setAttached] = useState<readonly Attached[]>([]);
  const reading = useAttachedReading(attached);
  const send = (words: string) => {
    if (words.trim() && !reading.size) assistant.start({ text: words.trim(), title: words.trim().slice(0, TITLE_LENGTH), model, context: attached.map((item) => item.ref) });
  };
  return (
    <div className="flex min-h-0 flex-1 flex-col justify-end gap-3 p-3">
      <div className="flex flex-col px-1">
        <p className="mb-2 text-lg font-medium text-ink-primary">{t("chat.new.title")}</p>
        <ul className="flex flex-col">
          {STARTERS.map((key) => (
            <li key={key}>
              <Pressable onClick={() => send(t(key))} className="focus-ring flex w-full items-center gap-2 py-2 text-left text-md text-ink-secondary transition-colors duration-fast hover:text-ink-primary">
                <Icon name="followUp" className="h-3 w-3 shrink-0 text-ink-muted" />
                {t(key)}
              </Pressable>
            </li>
          ))}
        </ul>
      </div>
      <AttachedChips items={attached} reading={reading} onRemove={(ref) => setAttached(attached.filter((item) => item.ref !== ref))} />
      <Composer
        value={text}
        onChange={setText}
        onSubmit={() => send(text)}
        placeholder={t("sessions.prompt.placeholder")}
        label={t("sessions.prompt")}
        busy={assistant.starting}
        holdSend={reading.size > 0}
        autoFocus
        leading={<AttachMenu onAttach={(items) => setAttached([...attached, ...items.filter((item) => !attached.some((other) => other.ref === item.ref))])} />}
        trailing={<ModelPicker value={model} onChange={setModel} />}
      />
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
  // The Mail agent's chat is always first, so its triggered runs are easy to get to.
  const chats = [...(sessions.data?.sessions ?? [])].sort((a, b) => Number(b.id === MAIL_AGENT) - Number(a.id === MAIL_AGENT));
  const options = chats.map((row) => ({ value: row.id, label: row.status === "waiting" ? t("chat.waitingLabel", { title: row.title }) : row.title }));
  // Only one panel ever exists, so pinning moves it instead of restarting the conversation.
  // Out from the edge it sits against that edge, so the pointer that called it is already on it.
  const attached = (assistant.pinned || assistant.peeking) && width >= SMALL_SCREEN;
  const place = attached ? { top: 0, right: 0, bottom: 0, borderRadius: 0 } : { top: Math.max(GAP, height - GAP - FLOATING_HEIGHT), right: GAP, bottom: GAP, borderRadius: GAP - 2 };
  // Out from the edge, it goes back when the person's done with it, unless they're mid-thought.
  // Its input focuses itself on opening, so focus only counts once they've used it.
  const used = useRef(false);
  const panel = useRef<HTMLElement>(null);
  const { peeking, setOpen } = assistant;
  useEffect(() => {
    if (!peeking) return;
    // The pointer that called it never crossed into it, so the panel's own leave event can't be trusted.
    const moved = (event: PointerEvent) => {
      const node = panel.current;
      if (!node || event.clientX >= node.getBoundingClientRect().left || node.querySelector("textarea")?.value) return;
      if (!used.current || !node.contains(document.activeElement)) setOpen(false);
    };
    window.addEventListener("pointermove", moved);
    return () => window.removeEventListener("pointermove", moved);
  }, [peeking, setOpen]);
  return (
    <SlidePanel
      attached={attached}
      place={place}
      ref={panel}
      onPointerDown={() => {
        used.current = true;
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && assistant.peeking) assistant.setOpen(false);
        else used.current = true;
      }}
      aria-label={t("chat.title")}
      data-testid="assistant-dock"
      data-pinned={assistant.pinned && attached}
      className={`fixed z-40 flex w-dock max-w-full flex-col overflow-hidden border border-line-subtle bg-surface-page ${attached ? `border-y-0 border-r-0 ${assistant.peeking ? "shadow-overlay" : ""}` : "shadow-overlay"}`}
    >
      <header className="flex h-topbar shrink-0 items-center gap-1 border-b border-line-subtle px-2">
        <div className="min-w-0 flex-1">
          {assistant.session && options.length ? <Select quiet label={t("chat.switch")} value={assistant.session} options={options} onChange={assistant.openSession} /> : <p className="px-2 text-md font-medium text-ink-primary">{t("chat.title")}</p>}
        </div>
        <IconButton icon="newChat" label={t("chat.new")} onClick={assistant.newChat} />
        {assistant.session ? <CompactAction session={assistant.session} /> : null}
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
      <div key={assistant.session ?? "new"} className="flex min-h-0 flex-1 animate-fade flex-col">{assistant.session ? <SessionChat id={assistant.session} /> : <NewChat />}</div>
    </SlidePanel>
  );
}

/** Makes room beside the page for the pinned chat, moving with it as it slides in. */
export function AssistantRoom() {
  const assistant = useAssistant();
  const pathname = usePathname();
  const { width } = useWindowSize();
  const showing = assistant.open && assistant.pinned && width >= SMALL_SCREEN && !pathname.startsWith("/agent/sessions/");
  return <Room width={showing ? light.layout.dock : null} />;
}

/** The chat, from anywhere in the app. It tucks into a small pill when it isn't needed. */
export function AssistantDock() {
  const assistant = useAssistant();
  const pathname = usePathname();
  const sessions = useSessions("");
  const waiting = useWaitingCount();
  const { width } = useWindowSize();
  const running = sessions.data?.running ?? 0;
  // The session page already is this conversation, and two live views of one chat would fight.
  if (pathname.startsWith("/agent/sessions/")) return null;
  return (
    <Presence>
      {assistant.open ? (
        <Panel key="panel" />
      ) : assistant.tucked && width >= SMALL_SCREEN ? (
        <Pressable key="aura" data-testid="assistant-aura" data-waiting={waiting > 0} aria-label={t("chat.openFromEdge")} onMouseEnter={() => assistant.setOpen(true)} onClick={() => assistant.setOpen(true)} className="assistant-aura focus-ring fixed bottom-0 right-0 top-0 z-40 w-aura" />
      ) : (
        <RiseButton key="pill" onClick={() => assistant.setOpen(true)} data-testid="assistant-pill" className="ai-glow focus-ring fixed bottom-4 right-4 z-40 flex items-center gap-2 rounded-full px-4 py-2 text-md font-medium text-ink-primary shadow-overlay">
          <Icon name="chat" />
          {t("chat.pill")}
          {waiting ? (
            <span className="flex items-center gap-1 text-sm tabular-nums text-accent-default">
              <StatusDot tone="waiting" />
              <Swap value={waiting}>{tn("chat.waitingCount", waiting)}</Swap>
            </span>
          ) : running ? (
            <StatusDot tone="running" />
          ) : null}
        </RiseButton>
      )}
    </Presence>
  );
}
