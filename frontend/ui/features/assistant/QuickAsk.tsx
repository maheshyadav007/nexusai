"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { desktopApi } from "@/ui/client/desktop";
import { useHomeReady, useHomeStatus, useLeadName } from "@/ui/client/home";
import { leaveFirstMessage, useCreateSession } from "@/ui/client/sessions";
import { useAgentCards } from "@/ui/client/work";
import { PreviewInApp } from "@/ui/features/documents/DocumentPreview";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Mascot } from "@/ui/primitives/Mascot";
import { BareTextarea, Pressable } from "@/ui/primitives/Pressable";
import { t } from "@/ui/strings";
import { SessionChat } from "./SessionChat";

/** What's sent: the selected text quoted, then the question about it. */
export function quickMessage(question: string, selection: string): string {
  const asked = question.trim();
  if (!selection) return asked;
  const quoted = selection.split(/\r?\n/).map((line) => `> ${line}`).join("\n");
  return `${quoted}\n\n${asked || t("quick.explain")}`;
}

const inApp = (link: string) => {
  const quick = desktopApi()?.quick;
  if (quick) void quick("open-in-app", link);
  else window.location.assign(link);
};

/** A theme duration, such as --motion-normal, in milliseconds. */
const motion = (name: "fast" | "normal") => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(`--motion-${name}`)) || 0;

/** Plays one of the theme's enter or leave animations on an element, from its start. */
function play(element: HTMLElement | null, animation: "animate-dialog-in" | "animate-dialog-out") {
  if (!element) return;
  element.classList.remove("animate-dialog-in", "animate-dialog-out");
  void element.offsetWidth;
  element.classList.add(animation);
}

/**
 * The box the desktop shortcut opens: one line to ask the lead agent something, with whatever
 * was selected in another app above it. Sending starts a new chat, which then answers here.
 */
export function QuickAsk() {
  const ready = useHomeReady();
  const home = useHomeStatus();
  const lead = useLeadName();
  const card = useAgentCards().data?.cards.find((item) => item.default);
  const create = useCreateSession();
  const { reset } = create;
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [selection, setSelection] = useState("");
  const [session, setSession] = useState<string | null>(null);
  const [last, setLast] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  // A close still fading out, which a quick press of the shortcut again must not finish.
  const closing = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const desktop = desktopApi();

  const focus = useCallback(() => requestAnimationFrame(() => input.current?.focus()), []);
  const fresh = useCallback((selected: string) => {
    setSession((current) => {
      if (current) setLast(current);
      return null;
    });
    setText("");
    setSelection(selected);
    reset();
    focus();
  }, [reset, focus]);

  // Each press of the shortcut is a new question, with what was selected at that moment.
  useEffect(() => {
    const api = desktopApi();
    const opened = (detail: { selection: string } | null) => {
      if (!detail) return;
      clearTimeout(closing.current);
      fresh(detail.selection);
      play(box.current, "animate-dialog-in");
    };
    const stop = api?.onQuickOpen?.((detail) => {
      opened(detail);
      void api.quick?.("take");
    });
    void api?.quick?.("take").then(opened).catch(() => {});
    return stop;
  }, [fresh]);

  // The box glides to the height of what's in it. The window, see-through around the box, grows
  // before the box does and shrinks after it, so the box is never cut off on the way.
  useEffect(() => {
    const content = inner.current, outer = root.current;
    if (!content || !outer) return;
    let shrink: ReturnType<typeof setTimeout> | undefined;
    let shown = 0;
    const observer = new ResizeObserver(() => {
      const border = box.current ? box.current.offsetHeight - box.current.clientHeight : 0;
      const next = Math.ceil(content.getBoundingClientRect().height) + border;
      // Measured, so it's set on the element as SafeMailFrame does, not written as a style.
      if (box.current) box.current.style.height = `${next}px`;
      const quick = desktopApi()?.quick;
      if (!quick) return;
      const style = getComputedStyle(outer);
      const wanted = next + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
      clearTimeout(shrink);
      if (wanted >= shown) void quick("resize", wanted);
      else shrink = setTimeout(() => void quick("resize", wanted), motion("normal"));
      shown = wanted;
    });
    observer.observe(content);
    return () => { observer.disconnect(); clearTimeout(shrink); };
  }, []);

  const close = useCallback(() => {
    const quick = desktopApi()?.quick;
    if (!quick) return;
    play(box.current, "animate-dialog-out");
    clearTimeout(closing.current);
    closing.current = setTimeout(() => void quick("hide"), motion("fast"));
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape" && !event.defaultPrevented) close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  const send = () => {
    const message = quickMessage(text, selection);
    if (!message || create.isPending) return;
    create.mutate({}, {
      onSuccess: (row) => {
        leaveFirstMessage(row.id, message);
        // SessionChat loads it once it's on screen; a copy fetched before then would never count.
        setSession(row.id);
      },
    });
  };

  const backToLast = () => {
    if (!last) return;
    // What changed while it was put away has to be fetched again.
    void client.invalidateQueries({ queryKey: ["session", last] });
    setSession(last);
    setLast(null);
  };

  // Links in an answer lead into the app, which has the room to show them.
  const followLinks = (event: MouseEvent) => {
    const link = (event.target as HTMLElement).closest("a[href]")?.getAttribute("href");
    if (!desktop || !link?.startsWith("/")) return;
    event.preventDefault();
    inApp(link);
  };

  const face = card ? <Mascot seed={card.mascot.seed} shape={card.mascot.style} name={lead} size="sm" /> : <span aria-hidden className="h-5 w-5 shrink-0" />;

  let body;
  if (home.isPending) body = null;
  else if (!ready) {
    body = (
      <div className="flex items-center justify-between gap-4 px-5 py-4">
        <p className="text-md text-ink-secondary">{t("quick.notReady")}</p>
        <Button onClick={() => inApp("/")}>{t("quick.openApp")}</Button>
      </div>
    );
  } else if (session) {
    body = (
      <>
        <header className="flex items-center gap-2 border-b border-line-subtle py-2 pl-4 pr-2">
          {face}
          <span className="min-w-0 flex-1 truncate text-md font-medium text-ink-primary">{lead}</span>
          <IconButton icon="openFull" label={t("quick.openInApp")} onClick={() => inApp(`/agent/sessions/${session}?view=full`)} />
          <IconButton icon="newChat" label={t("chat.new")} onClick={() => fresh("")} />
          {desktop ? <IconButton icon="close" label={t("quick.close")} tooltip={false} onClick={close} /> : null}
        </header>
        <div className="flex max-h-quick-height flex-col animate-fade">
          <SessionChat id={session} />
        </div>
      </>
    );
  } else {
    body = (
      <>
        {selection ? (
          <div data-testid="quick-selection" className="mx-4 mt-4 flex items-start gap-2 rounded-md bg-surface-sunken py-2 pl-3 pr-1 animate-fade">
            <Icon name="followUp" className="mt-px h-4 w-4 shrink-0 text-ink-muted" />
            <p className="line-clamp-3 min-w-0 flex-1 whitespace-pre-wrap text-sm text-ink-secondary">{selection}</p>
            <IconButton icon="close" label={t("quick.removeSelection")} tooltip={false} onClick={() => { setSelection(""); focus(); }} />
          </div>
        ) : null}
        <form className="flex items-center gap-3 py-4 pl-5 pr-4" onSubmit={(event) => { event.preventDefault(); send(); }}>
          {face}
          <BareTextarea
            ref={input}
            aria-label={t("quick.label", { agent: lead })}
            placeholder={t(selection ? "quick.placeholder.selection" : "quick.placeholder")}
            rows={1}
            value={text}
            // eslint-disable-next-line jsx-a11y/no-autofocus -- the box exists to be typed into
            autoFocus
            disabled={create.isPending}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                send();
              }
            }}
            className="min-w-0 flex-1 py-1 text-lg outline-none"
          />
          {last ? <Button variant="quiet" className="shrink-0" onClick={backToLast}>{t("quick.lastChat")}</Button> : null}
          <Pressable
            type="submit"
            aria-label={t("sessions.send")}
            disabled={create.isPending || !quickMessage(text, selection)}
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accent-default text-accent-on transition-colors duration-fast hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Icon name={create.isPending ? "loading" : "moveUp"} className={`h-4 w-4 ${create.isPending ? "animate-spin motion-reduce:animate-none" : ""}`} />
          </Pressable>
        </form>
        {create.isError ? <div className="px-5 pb-4"><ErrorState title={t("sessions.failed")} description={create.error.message} /></div> : null}
      </>
    );
  }

  return (
    <PreviewInApp open={inApp}>
      {/* The window is see-through around the box; the padding is room for its shadow. */}
      <div ref={root} className="flex min-h-screen flex-col justify-end p-3" onClickCapture={followLinks}>
        <section
          ref={box}
          aria-label={t("quick.title", { agent: lead })}
          className="quick-box mx-auto w-full max-w-quick overflow-hidden rounded-lg border border-line-subtle bg-surface-raised shadow-overlay"
        >
          {/* flow-root, so a first child's margin is measured inside it, not outside. */}
          <div ref={inner} className="flow-root">{body}</div>
        </section>
      </div>
    </PreviewInApp>
  );
}
