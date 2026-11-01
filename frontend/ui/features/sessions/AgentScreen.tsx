"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, type UIMessage } from "ai";
import { useEffect, useMemo, useRef, useState } from "react";
import { takeFirstMessage, useApprovals, useModelCall, useSession, useStopSession } from "@/ui/client/sessions";
import { useSessionContext, useSetContext } from "@/ui/client/work";
import { ApprovalDetails } from "@/ui/shell/ApprovalQueue";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { IconButton } from "@/ui/primitives/IconButton";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Textarea } from "@/ui/primitives/Input";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { TextLink } from "@/ui/primitives/TextLink";
import { t, type StringKey } from "@/ui/strings";
import { SESSION_STATES } from "./SessionsScreen";

interface ToolPart {
  type: string;
  toolCallId: string;
  state: string;
  input?: unknown;
  output?: unknown;
  errorText?: string;
}

const TOOL_LABELS: Readonly<Record<string, StringKey>> = {
  read_file: "tools.read_file",
  write_file: "tools.write_file",
  edit_file: "tools.edit_file",
  run_command: "tools.run_command",
  search_mail: "tools.search_mail",
  read_thread: "tools.read_thread",
};

const TOOL_STATES: Readonly<Record<string, { label: StringKey; tone: "running" | "waiting" | "done" | "failed" | "idle" }>> = {
  "input-streaming": { label: "tools.state.preparing", tone: "running" },
  "input-available": { label: "tools.state.running", tone: "running" },
  "approval-requested": { label: "tools.state.waiting", tone: "waiting" },
  "approval-responded": { label: "tools.state.running", tone: "running" },
  "output-available": { label: "tools.state.done", tone: "done" },
  "output-denied": { label: "tools.state.denied", tone: "idle" },
  "output-error": { label: "tools.state.failed", tone: "failed" },
};

const asText = (value: unknown) => (typeof value === "string" ? value : JSON.stringify(value, null, 2));

function ToolCallCard({ part }: { part: ToolPart }) {
  const approvals = useApprovals();
  const name = part.type.slice("tool-".length);
  const label = TOOL_LABELS[name];
  const state = TOOL_STATES[part.state] ?? { label: "tools.state.running" as const, tone: "running" as const };
  const pending = approvals.data?.approvals.find((approval) => approval.tool_call_id === part.toolCallId);
  return (
    <section data-testid="tool-call" className="flex flex-col gap-2 rounded-md border border-line-subtle bg-surface-raised p-3">
      <header className="flex items-center justify-between gap-3">
        <h2 className="min-w-0 truncate text-md font-medium text-ink-primary">{label ? t(label) : name}</h2>
        <span className="flex shrink-0 items-center gap-2 text-sm text-ink-secondary">
          <StatusDot tone={state.tone} />
          {t(state.label)}
        </span>
      </header>
      {pending ? (
        <ApprovalDetails approval={pending} />
      ) : (
        <details className="text-sm text-ink-secondary">
          <summary className="focus-ring cursor-pointer rounded-sm">{t("tools.details")}</summary>
          <pre className="mt-2 max-h-popover overflow-auto whitespace-pre-wrap break-words rounded-md bg-surface-sunken p-2 font-mono text-sm">{asText(part.input)}</pre>
          {part.output !== undefined ? <pre data-testid="tool-output" className="mt-2 max-h-popover overflow-auto whitespace-pre-wrap break-words rounded-md bg-surface-sunken p-2 font-mono text-sm">{asText(part.output)}</pre> : null}
        </details>
      )}
      {part.errorText ? <p className="text-sm text-status-danger">{part.errorText}</p> : null}
    </section>
  );
}

function MessageView({ message }: { message: UIMessage }) {
  const mine = message.role === "user";
  return (
    <article data-testid={mine ? "user-message" : "agent-message"} className={`flex flex-col gap-2 ${mine ? "items-end" : "items-stretch"}`}>
      {message.parts.map((part, index) => {
        if (part.type === "text") {
          return (
            <div key={index} className={`whitespace-pre-wrap break-words text-md text-ink-primary ${mine ? "rounded-md bg-surface-sunken px-3 py-2" : ""}`}>
              {part.text}
            </div>
          );
        }
        if (part.type === "reasoning") {
          return (
            <details key={index} className="text-sm text-ink-muted">
              <summary className="focus-ring cursor-pointer rounded-sm">{t("sessions.thinking")}</summary>
              <p className="mt-1 whitespace-pre-wrap">{part.text}</p>
            </details>
          );
        }
        if (part.type.startsWith("tool-")) return <ToolCallCard key={index} part={part as unknown as ToolPart} />;
        return null;
      })}
    </article>
  );
}

function FinalPrompt({ session }: { session: string }) {
  const [open, setOpen] = useState(false);
  const [masked, setMasked] = useState(true);
  const call = useModelCall(session, open);
  return (
    <Dialog title={t("sessions.prompt.title")} description={t("sessions.prompt.description")} shape="drawer" open={open} onOpenChange={setOpen} trigger={<Button variant="quiet">{t("sessions.prompt.open")}</Button>}>
      <div className="flex flex-col gap-3 overflow-y-auto">
        <div>
          <Button onClick={() => setMasked((current) => !current)}>{t(masked ? "sessions.prompt.showReal" : "sessions.prompt.showMasked")}</Button>
        </div>
        {call.isPending ? <Skeleton className="h-6 w-full" /> : null}
        {call.isError ? <p className="text-md text-ink-muted">{t("sessions.prompt.none")}</p> : null}
        {call.data?.layers.map((layer) => (
          <section key={layer.name} data-testid="prompt-layer">
            <h3 className="mb-1 text-md font-medium text-ink-primary">{layer.name}</h3>
            <pre className="max-h-popover overflow-auto whitespace-pre-wrap break-words rounded-md bg-surface-sunken p-2 font-mono text-sm text-ink-secondary">{masked ? layer.masked : layer.real}</pre>
          </section>
        ))}
      </div>
    </Dialog>
  );
}

function ContextChips({ id }: { id: string }) {
  const context = useSessionContext(id);
  const setContext = useSetContext();
  const items = context.data?.items ?? [];
  if (!items.length) return null;
  return (
    <ul aria-label={t("sessions.context")} className="flex flex-wrap items-center gap-2">
      {items.map((item) => (
        <li key={item.ref} data-testid="context-chip" className="flex items-center gap-1">
          <Badge>{item.label}</Badge>
          <IconButton icon="close" tooltip={false} label={t("sessions.context.remove", { label: item.label })} onClick={() => setContext.mutate({ id, context: items.filter((other) => other.ref !== item.ref).map((other) => other.ref) })} />
        </li>
      ))}
    </ul>
  );
}

export function Conversation({ id, initial, active }: { id: string; initial: UIMessage[]; active: boolean }) {
  const transport = useMemo(
    () =>
      new DefaultChatTransport<UIMessage>({
        api: "/api/sessions/chat",
        // The backend keeps the history, so it only needs what was just typed.
        prepareSendMessagesRequest: ({ messages }) => {
          const last = messages[messages.length - 1];
          const text = last?.parts.flatMap((part) => (part.type === "text" ? [part.text] : [])).join("\n") ?? "";
          return { body: { id, text } };
        },
      }),
    [id],
  );
  const chat = useChat({ id, transport, messages: initial, resume: active });
  const stop = useStopSession();
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const { sendMessage } = chat;
  useEffect(() => {
    // useChat stops the chat when an effect is cleaned up, which React's checks do once on mount.
    const timer = setTimeout(() => {
      const first = takeFirstMessage(id);
      if (first) void sendMessage({ text: first });
    }, 0);
    return () => clearTimeout(timer);
  }, [id, sendMessage]);
  const busy = chat.status === "submitted" || chat.status === "streaming";
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [chat.messages]);
  const send = () => {
    if (!text.trim() || busy) return;
    void chat.sendMessage({ text });
    setText("");
  };
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div role="log" aria-label={t("sessions.conversation")} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
        {chat.messages.map((message) => (
          <MessageView key={message.id} message={message} />
        ))}
        <div ref={end} />
      </div>
      <ContextChips id={id} />
      {chat.error ? <ErrorState title={t("sessions.failed")} description={chat.error.message} /> : null}
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <Textarea
          aria-label={t("sessions.prompt")}
          placeholder={t("sessions.prompt.placeholder")}
          rows={2}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
        />
        <div className="flex items-center justify-between gap-2">
          <FinalPrompt session={id} />
          {busy ? (
            <Button variant="danger" loading={stop.isPending} onClick={() => stop.mutate(id)}>
              {t("sessions.stop")}
            </Button>
          ) : (
            <Button type="submit" variant="primary" disabled={!text.trim()}>
              {t("sessions.send")}
            </Button>
          )}
        </div>
      </form>
    </div>
  );
}

export function AgentScreen({ id }: { id: string }) {
  const session = useSession(id);
  // Fixed once loaded: the live conversation belongs to useChat from here on.
  const [start, setStart] = useState<{ messages: UIMessage[]; active: boolean } | null>(null);
  useEffect(() => {
    if (session.data && !start) setStart({ messages: session.data.messages as unknown as UIMessage[], active: session.data.active });
  }, [session.data, start]);
  if (session.isError) {
    return (
      <div className="mx-auto flex max-w-content flex-col gap-3 p-6">
        <ErrorState title={t("sessions.error")} description={session.error.message} />
        <TextLink href="/agent/sessions" className="self-start">{t("nav.sessions")}</TextLink>
      </div>
    );
  }
  if (!session.data || !start) return <div aria-busy className="mx-auto max-w-content p-6"><Skeleton className="h-6 w-full" /></div>;
  const row = session.data.session;
  const state = SESSION_STATES[row.status];
  return (
    <div className="mx-auto flex h-full max-w-content flex-col gap-3 p-6">
      <header className="flex items-center justify-between gap-3">
        <h1 className="min-w-0 truncate font-serif text-display text-ink-primary">{row.title}</h1>
        {state ? (
          <p role="status" data-testid="session-status" className="flex shrink-0 items-center gap-2 text-sm text-ink-secondary">
            <StatusDot tone={state.tone} />
            {t(state.label)}
          </p>
        ) : null}
      </header>
      {row.untrusted ? <p className="text-sm text-ink-muted">{t("sessions.untrusted")}</p> : null}
      <Conversation key={id} id={id} initial={start.messages} active={start.active} />
    </div>
  );
}
