"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, type UIMessage } from "ai";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { useTimeOnly } from "@/ui/client/format";
import { takeFirstMessage, useAnswerSession, useApprovals, useModelCall, useStopSession } from "@/ui/client/sessions";
import { useChannel, useDismissChannel, useSessionContext, useSetContext } from "@/ui/client/work";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { FADE_RISE, QUICK } from "@/ui/primitives/motion";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Tooltip } from "@/ui/primitives/Tooltip";
import { t } from "@/ui/strings";
import { AnsweredQuestion, ApprovalCard, MailCard, QuestionCard, ResultCard } from "./Cards";
import { Composer } from "./Composer";
import { Markdown } from "./Markdown";
import { failureOf, followUpsOf, isFinished, textOf, timeOf, toBlocks, toolName, type ToolPart } from "./parts";
import { ThinkingTrace } from "./ThinkingTrace";

const COPIED_MS = 1500;
// Near enough to the end to keep following what arrives.
const FOLLOW_WITHIN_PX = 96;
const ANSWER_PREFIX = "They answered: ";

function ActionButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <Tooltip content={label}>
      <button type="button" aria-label={label} onClick={onClick} className="focus-ring inline-flex h-5 w-5 items-center justify-center rounded-sm text-ink-muted transition-colors duration-fast hover:bg-surface-sunken hover:text-ink-primary">
        {children}
      </button>
    </Tooltip>
  );
}

function CopyAction({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <ActionButton
      label={copied ? t("chat.copied") : label}
      onClick={() =>
        void navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), COPIED_MS);
        })
      }
    >
      <Icon name={copied ? "check" : "copy"} className="h-3 w-3" />
    </ActionButton>
  );
}

function MessageTime({ value }: { value: string | null }) {
  const format = useTimeOnly();
  return value ? <time dateTime={value} className="text-sm tabular-nums text-ink-faint">{format(value)}</time> : null;
}

function UserMessage({ message, canEdit, onEdit }: { message: UIMessage; canEdit: boolean; onEdit: (text: string) => void }) {
  const text = textOf(message);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text);
  if (editing) {
    return (
      <form
        data-testid="user-message-edit"
        className="flex flex-col gap-2 rounded-lg border border-line-strong bg-surface-raised p-3"
        onSubmit={(event) => {
          event.preventDefault();
          setEditing(false);
          if (draft.trim() && draft !== text) onEdit(draft.trim());
        }}
      >
        <textarea aria-label={t("chat.edit")} autoFocus value={draft} onChange={(event) => setDraft(event.target.value)} className="grow-field focus-ring w-full resize-none bg-transparent text-md text-ink-primary" />
        <p className="text-sm text-ink-muted">{t("chat.edit.note")}</p>
        <div className="flex justify-end gap-2">
          <Button variant="quiet" onClick={() => setEditing(false)}>
            {t("home.picker.cancel")}
          </Button>
          <Button type="submit" variant="primary" disabled={!draft.trim()}>
            {t("chat.edit.save")}
          </Button>
        </div>
      </form>
    );
  }
  return (
    <motion.article {...FADE_RISE} data-testid="user-message" className="group flex flex-col items-end gap-1">
      <div className="max-w-full whitespace-pre-wrap break-words rounded-lg bg-surface-sunken px-3 py-2 text-md text-ink-primary">{text}</div>
      <div className="flex items-center gap-1 opacity-0 transition-opacity duration-fast focus-within:opacity-100 group-hover:opacity-100">
        <MessageTime value={timeOf(message)} />
        <CopyAction text={text} label={t("chat.copy")} />
        {canEdit ? (
          <ActionButton
            label={t("chat.edit")}
            onClick={() => {
              setDraft(text);
              setEditing(true);
            }}
          >
            <Icon name="edit" className="h-3 w-3" />
          </ActionButton>
        ) : null}
      </div>
    </motion.article>
  );
}

function QuestionPart({ part, session }: { part: ToolPart; session: string }) {
  const answer = useAnswerSession();
  const channel = useChannel();
  const dismiss = useDismissChannel();
  const [said, setSaid] = useState<string | null>(null);
  const input = part.input ?? {};
  const question = String(input.question ?? "");
  const options = Array.isArray(input.options) ? input.options.map(String) : [];
  if (isFinished(part)) {
    const output = typeof part.output === "string" ? part.output : "";
    return <AnsweredQuestion question={question} answer={output.startsWith(ANSWER_PREFIX) ? output.slice(ANSWER_PREFIX.length) : null} />;
  }
  if (said) return <AnsweredQuestion question={question} answer={said} />;
  const open = channel.data?.messages.find((message) => message.session === session && message.kind === "ask");
  const refused = answer.error instanceof ApiRequestError ? answer.error.detail.message : answer.error ? t("chat.question.failed") : null;
  return (
    <QuestionCard
      question={question}
      options={options}
      multiple={input.multiple === true}
      pending={answer.isPending}
      error={refused}
      onAnswer={(text) => answer.mutate({ id: session, answer: text }, { onSuccess: () => setSaid(text) })}
      {...(open ? { onSkip: () => dismiss.mutate(open.id) } : {})}
    />
  );
}

function AssistantMessage({ message, session, running, isLast, onFollowUp, showFollowUps }: { message: UIMessage; session: string; running: boolean; isLast: boolean; onFollowUp: (text: string) => void; showFollowUps: boolean }) {
  const approvals = useApprovals();
  const pending = useMemo(() => new Map((approvals.data?.approvals ?? []).filter((item) => item.session === session).map((item) => [item.tool_call_id, item])), [approvals.data, session]);
  const blocks = toBlocks(message, new Set(pending.keys()));
  const text = textOf(message);
  const failure = failureOf(message);
  const followUps = followUpsOf(message);
  const settled = !running || !isLast;
  return (
    <article data-testid="agent-message" className="group flex flex-col gap-3">
      {blocks.map((block) => {
        if (block.kind === "text") return <Markdown key={block.key} text={block.text} />;
        if (block.kind === "trace") return <ThinkingTrace key={block.key} steps={block.steps} running={running && isLast && block.key === blocks[blocks.length - 1]?.key} />;
        const { part } = block;
        const name = toolName(part);
        const approval = pending.get(part.toolCallId);
        if (name === "ask_user") return <QuestionPart key={block.key} part={part} session={session} />;
        if (name === "send_mail") return <MailCard key={block.key} part={part} approval={approval} />;
        if (approval && !["create_task", "create_reminder", "create_category", "create_agent", "propose_task", "propose_reminder", "draft_reply"].includes(name)) return <ApprovalCard key={block.key} approval={approval} />;
        return <ResultCard key={block.key} part={part} approval={approval} />;
      })}
      {failure ? <ErrorState title={t("sessions.failed")} description={failure} /> : null}
      {settled && text ? (
        <div className="flex items-center gap-1 opacity-0 transition-opacity duration-fast focus-within:opacity-100 group-hover:opacity-100">
          <CopyAction text={text} label={t("chat.copy")} />
          <MessageTime value={timeOf(message)} />
        </div>
      ) : null}
      {showFollowUps && settled && followUps.length ? (
        <ul aria-label={t("chat.followUps")} className="flex flex-col border-t border-line-subtle">
          {followUps.map((question) => (
            <li key={question} className="border-b border-line-subtle">
              <button type="button" onClick={() => onFollowUp(question)} className="focus-ring flex w-full items-center gap-2 py-2 text-left text-md text-ink-secondary transition-colors duration-fast hover:text-ink-primary">
                <Icon name="followUp" className="h-3 w-3 shrink-0 text-ink-muted" />
                {question}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

function ContextChips({ id }: { id: string }) {
  const context = useSessionContext(id);
  const setContext = useSetContext();
  const items = context.data?.items ?? [];
  if (!items.length) return null;
  return (
    <ul aria-label={t("sessions.context")} className="flex flex-wrap items-center gap-1">
      {items.map((item) => (
        <li key={item.ref} data-testid="context-chip" className="flex max-w-full items-center gap-1 rounded-md border border-line-subtle bg-surface-raised py-px pl-2 pr-1 text-sm text-ink-secondary">
          <span className="min-w-0 truncate">{item.label}</span>
          <button type="button" aria-label={t("sessions.context.remove", { label: item.label })} onClick={() => setContext.mutate({ id, context: items.filter((other) => other.ref !== item.ref).map((other) => other.ref) })} className="focus-ring rounded-sm p-px text-ink-muted transition-colors duration-fast hover:text-ink-primary">
            <Icon name="close" className="h-3 w-3" />
          </button>
        </li>
      ))}
    </ul>
  );
}

export function FinalPrompt({ session }: { session: string }) {
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

/** The one conversation view: the dock, the session page and setup all use it. */
export function ChatView({ id, initial, active, readOnly = false, footer }: { id: string; initial: UIMessage[]; active: boolean; readOnly?: boolean; footer?: React.ReactNode }) {
  const editIndex = useRef<number | null>(null);
  const transport = useMemo(
    () =>
      new DefaultChatTransport<UIMessage>({
        api: "/api/sessions/chat",
        // The backend keeps the history, so it only needs what was just typed.
        prepareSendMessagesRequest: ({ messages }) => {
          const last = messages[messages.length - 1];
          const text = last?.parts.flatMap((part) => (part.type === "text" ? [part.text] : [])).join("\n") ?? "";
          const body = { id, text, ...(editIndex.current === null ? {} : { edit_index: editIndex.current }) };
          editIndex.current = null;
          return { body };
        },
      }),
    [id],
  );
  const chat = useChat({ id, transport, messages: initial, resume: active });
  const { sendMessage, setMessages, messages, status } = chat;
  const stop = useStopSession();
  const answer = useAnswerSession();
  const approvals = useApprovals();
  const [text, setText] = useState("");
  const log = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const [away, setAway] = useState(false);

  const say = (words: string) => void sendMessage({ text: words, metadata: { time: new Date().toISOString() } });
  useEffect(() => {
    // useChat stops the chat when an effect is cleaned up, which React's checks do once on mount.
    const timer = setTimeout(() => {
      const first = takeFirstMessage(id);
      if (first) void sendMessage({ text: first, metadata: { time: new Date().toISOString() } });
    }, 0);
    return () => clearTimeout(timer);
  }, [id, sendMessage]);

  const working = status === "submitted" || status === "streaming";
  const tools = messages.flatMap((message) => message.parts.filter((part) => part.type.startsWith("tool-"))) as unknown as ToolPart[];
  const asking = tools.some((part) => toolName(part) === "ask_user" && !isFinished(part));
  const deciding = (approvals.data?.approvals ?? []).some((item) => item.session === id);
  const waiting = working && (asking || deciding);

  useEffect(() => {
    if (following.current) log.current?.scrollTo?.({ top: log.current.scrollHeight });
  }, [messages]);

  const submit = () => {
    const words = text.trim();
    if (!words) return;
    if (asking) {
      answer.mutate({ id, answer: words });
      setText("");
      return;
    }
    if (working) return;
    say(words);
    following.current = true;
    setText("");
  };
  const edit = (index: number, words: string) => {
    const before = messages.slice(0, index).filter((message) => message.role === "user").length;
    editIndex.current = before;
    setMessages(messages.slice(0, index));
    say(words);
  };
  const lastAssistant = messages.findLastIndex((message) => message.role === "assistant");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="relative min-h-0 flex-1">
        <div
          ref={log}
          role="log"
          aria-label={t("sessions.conversation")}
          onScroll={(event) => {
            const box = event.currentTarget;
            following.current = box.scrollHeight - box.scrollTop - box.clientHeight < FOLLOW_WITHIN_PX;
            setAway(!following.current);
          }}
          className="flex h-full flex-col gap-3 overflow-y-auto p-4"
        >
          {messages.map((message, index) =>
            message.role === "user" ? (
              <UserMessage key={message.id} message={message} canEdit={!readOnly && !working} onEdit={(words) => edit(index, words)} />
            ) : (
              <AssistantMessage key={message.id} message={message} session={id} running={working && !waiting} isLast={index === messages.length - 1} showFollowUps={index === lastAssistant && !working && !readOnly} onFollowUp={say} />
            ),
          )}
          {status === "submitted" && messages[messages.length - 1]?.role === "user" ? (
            <p data-testid="thinking-start" className="flex items-center gap-2 py-1 text-md text-ink-muted">
              <Icon name="thinking" className="h-4 w-4 animate-working motion-reduce:animate-none" />
              {t("chat.thinking")}
            </p>
          ) : null}
        </div>
        <AnimatePresence>
          {away ? (
            <motion.button
              type="button"
              {...FADE_RISE}
              transition={QUICK}
              aria-label={t("chat.toLatest")}
              onClick={() => {
                following.current = true;
                setAway(false);
                log.current?.scrollTo?.({ top: log.current.scrollHeight, behavior: "smooth" });
              }}
              className="focus-ring absolute bottom-2 left-1/2 flex h-6 w-6 -translate-x-1/2 items-center justify-center rounded-full border border-line-subtle bg-surface-raised text-ink-secondary shadow-raised"
            >
              <Icon name="moveDown" className="h-3 w-3" />
            </motion.button>
          ) : null}
        </AnimatePresence>
      </div>
      {readOnly ? (
        <p className="border-t border-line-subtle p-4 text-sm text-ink-muted">{t("sessions.selfRunning")}</p>
      ) : (
        <div className="flex flex-col gap-2 p-3">
          <ContextChips id={id} />
          {chat.error ? <ErrorState title={t("sessions.failed")} description={chat.error.message} /> : null}
          <Composer
            value={text}
            onChange={setText}
            onSubmit={submit}
            busy={working && !asking}
            onStop={() => stop.mutate(id)}
            stopping={stop.isPending}
            disabled={deciding && !asking}
            placeholder={t(asking ? "chat.placeholder.answer" : deciding ? "chat.placeholder.decide" : "sessions.prompt.placeholder")}
            label={t("sessions.prompt")}
          />
          {footer}
        </div>
      )}
    </div>
  );
}
