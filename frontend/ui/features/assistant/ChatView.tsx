"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, type UIMessage } from "ai";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiRequestError, query } from "@/ui/client/api";
import { useEvents } from "@/ui/client/events";
import { useTimeOnly } from "@/ui/client/format";
import { groupApprovals, takeFirstMessage, useAnswerSession, useApprovals, useChooseVersion, useModelCall, useRateMessage, useSession, useSetSessionModel, useStopSession } from "@/ui/client/sessions";
import { useChannel, useCompactSession, useDismissChannel, useSessionContext, useSetContext } from "@/ui/client/work";
import { Icon } from "@/ui/icons";
import { useDateTime } from "@/ui/client/format";
import { MessageSources, useOpenSource } from "./MessageSources";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { WavyDivider } from "@/ui/primitives/WavyDivider";
import type { MenuItem } from "@/ui/primitives/Menu";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Presence, Rise, RiseButton, Swap } from "@/ui/primitives/Motion";
import { Pressable } from "@/ui/primitives/Pressable";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { useToast } from "@/ui/primitives/Toast";
import { Tooltip } from "@/ui/primitives/Tooltip";
import { t, type StringKey } from "@/ui/strings";
import { AnsweredQuestion, ApprovalGroupCard, MailCard, QuestionCard, ResultCard, TriageCard } from "./Cards";
import { AttachedChips, AttachMenu, ModelPicker, useAttachedReading, type Attached } from "./ChatControls";
import { Composer } from "./Composer";
import { Markdown } from "./Markdown";
import { factsOf, failureOf, followUpsOf, sourcesOf, isFinished, mergeResults, textOf, timeOf, toBlocks, toolName, type ToolPart, type Versions } from "./parts";
import { ThinkingTrace } from "./ThinkingTrace";

const COPIED_MS = 1500;
// Near enough to the end to keep following what arrives.
const FOLLOW_WITHIN_PX = 96;
const ANSWER_PREFIX = "They answered: ";
// Written the way the person would say it, with a small line saying what really sent it.
const tokensOf = (count: number) => (count >= 1000 ? `${Math.round(count / 1000)}K` : String(count));

const ORIGIN_LABEL: Readonly<Record<string, StringKey>> = {
  mail: "chat.origin.mail",
  "mail-hourly": "chat.origin.hourly",
  "mail-learn": "chat.origin.learn",
  setup: "chat.origin.setup",
  schedule: "chat.origin.schedule",
  event: "chat.origin.event",
};

function ActionButton({ label, hint, pressed, disabled, onClick, children }: { label: string; hint?: string; pressed?: boolean; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <Tooltip content={hint ?? label}>
      <Pressable aria-label={label} {...(pressed === undefined ? {} : { "aria-pressed": pressed })} disabled={disabled} onClick={onClick} className={`inline-flex h-5 w-5 items-center justify-center rounded-sm transition-colors duration-fast hover:bg-surface-sunken hover:text-ink-primary disabled:cursor-not-allowed disabled:text-ink-faint ${pressed ? "text-ink-primary" : "text-ink-muted"}`}>
        {children}
      </Pressable>
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
      <Swap value={copied}>
        <Icon name={copied ? "check" : "copy"} className="h-3 w-3" />
      </Swap>
    </ActionButton>
  );
}

function MessageTime({ value }: { value: string | null }) {
  const format = useTimeOnly();
  return value ? <time dateTime={value} className="text-sm tabular-nums text-ink-faint">{format(value)}</time> : null;
}

function UserMessage({ message, onEdit }: { message: UIMessage; onEdit: (text: string) => void }) {
  const text = textOf(message);
  const { origin } = factsOf(message);
  const source = origin ? ORIGIN_LABEL[origin] : undefined;
  return (
    <Rise as="article" data-testid="user-message" className="group flex flex-col items-end gap-1">
      <div className="max-w-full whitespace-pre-wrap break-words rounded-lg bg-surface-sunken px-3 py-2 text-md text-ink-primary">{text}</div>
      {source ? <p data-testid="message-origin" className="text-sm text-ink-muted">{t(source)}</p> : null}
      <div className="flex items-center gap-1 opacity-0 transition-opacity duration-fast focus-within:opacity-100 group-hover:opacity-100">
        <MessageTime value={timeOf(message)} />
        <CopyAction text={text} label={t("chat.copy")} />
        <ActionButton label={t("chat.edit")} onClick={() => onEdit(text)}>
          <Icon name="edit" className="h-3 w-3" />
        </ActionButton>
      </div>
    </Rise>
  );
}

function Rating({ turn, initial }: { turn: number; initial: "up" | "down" | null | undefined }) {
  const rate = useRateMessage();
  const [value, setValue] = useState(initial ?? null);
  const choose = (choice: "up" | "down") => {
    const before = value;
    const next = value === choice ? null : choice;
    setValue(next);
    rate.mutate({ turn, value: next }, { onError: () => setValue(before) });
  };
  return (
    <>
      <ActionButton label={t("chat.like")} pressed={value === "up"} onClick={() => choose("up")}>
        <Icon name="like" className="h-3 w-3" />
      </ActionButton>
      <ActionButton label={t("chat.dislike")} pressed={value === "down"} onClick={() => choose("down")}>
        <Icon name="dislike" className="h-3 w-3" />
      </ActionButton>
    </>
  );
}

function VersionSwitcher({ versions, disabled, onChoose }: { versions: Versions; disabled: boolean; onChoose: (turn: number) => void }) {
  const { turns, current } = versions;
  const go = (index: number) => {
    const turn = turns[index];
    if (turn !== undefined) onChoose(turn);
  };
  return (
    <span data-testid="versions" className="flex items-center text-sm tabular-nums text-ink-muted">
      <ActionButton label={t("chat.version.previous")} disabled={disabled || current === 0} onClick={() => go(current - 1)}>
        <Icon name="previous" className="h-3 w-3" />
      </ActionButton>
      {t("chat.version.count", { current: current + 1, total: turns.length })}
      <ActionButton label={t("chat.version.next")} disabled={disabled || current === turns.length - 1} onClick={() => go(current + 1)}>
        <Icon name="chevronRight" className="h-3 w-3" />
      </ActionButton>
    </span>
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

function AssistantMessage({ message, session, running, isLast, onFollowUp, showFollowUps, canRetry, onRetry, onChooseVersion }: { message: UIMessage; session: string; running: boolean; isLast: boolean; onFollowUp: (text: string) => void; showFollowUps: boolean; canRetry: boolean; onRetry: () => void; onChooseVersion: (turn: number) => void }) {
  const approvals = useApprovals();
  const pending = useMemo(() => new Map((approvals.data?.approvals ?? []).filter((item) => item.session === session).map((item) => [item.tool_call_id, item])), [approvals.data, session]);
  const blocks = toBlocks(message, new Set(pending.keys()));
  const merged = mergeResults(blocks, pending);
  const groups = groupApprovals([...pending.values()]);
  const text = textOf(message);
  const failure = failureOf(message);
  const followUps = followUpsOf(message);
  const sources = sourcesOf(message);
  const openSource = useOpenSource();
  const settled = !running || !isLast;
  const { turn, feedback, versions, thread } = factsOf(message);
  const menu: MenuItem[] = [
    ...(text ? [{ id: "copy", label: t("menu.copy"), onSelect: () => void navigator.clipboard.writeText(text) }] : []),
    ...(canRetry ? [{ id: "retry", label: t("menu.retry"), icon: "retry" as const, onSelect: onRetry }] : []),
  ];
  return (
    <ContextMenu items={settled ? menu : []}>
    <article data-testid="agent-message" className="group flex flex-col gap-3">
      {merged.map((block) => {
        if (block.kind === "text") return <Markdown key={block.key} text={block.text} sources={sources} onOpenSource={openSource} />;
        if (block.kind === "trace") return <ThinkingTrace key={block.key} steps={block.steps} running={running && isLast && block.key === blocks[blocks.length - 1]?.key} />;
        if (block.kind === "results") return <ResultCard key={block.key} parts={block.parts} />;
        const { part } = block;
        const name = toolName(part);
        if (name === "ask_user") return <QuestionPart key={block.key} part={part} session={session} />;
        if (name === "send_mail") return <MailCard key={block.key} part={part} approval={pending.get(part.toolCallId)} />;
        if (name === "record_triage") return <TriageCard key={block.key} part={part} thread={thread} />;
        // The first of a group speaks for the rest.
        const group = groups.find((items) => items.some((item) => item.tool_call_id === part.toolCallId));
        return group?.[0]?.tool_call_id === part.toolCallId ? <ApprovalGroupCard key={block.key} approvals={group} /> : null;
      })}
      {failure ? <ErrorState title={t("sessions.failed")} description={failure} /> : null}
      {settled && !pending.size && merged.length + (failure ? 1 : 0) > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
        {/* It stays in view, because the rest of the bar only shows on hover. */}
        <MessageSources sources={sources} />
        <div className="flex items-center gap-1 opacity-0 transition-opacity duration-fast focus-within:opacity-100 group-hover:opacity-100">
          {text ? <CopyAction text={text} label={t("chat.copy")} /> : null}
          {turn !== undefined ? <Rating turn={turn} initial={feedback} /> : null}
          {canRetry ? (
            <ActionButton label={t("chat.retry")} hint={t("chat.retry.hint")} onClick={onRetry}>
              <Icon name="retry" className="h-3 w-3" />
            </ActionButton>
          ) : null}
          {versions && isLast ? <VersionSwitcher versions={versions} disabled={!canRetry} onChoose={onChooseVersion} /> : null}
          <MessageTime value={timeOf(message)} />
        </div>
        </div>
      ) : null}
      {showFollowUps && settled && followUps.length ? (
        <ul aria-label={t("chat.followUps")} className="flex flex-col">
          {followUps.map((question) => (
            <li key={question}>
              <Pressable onClick={() => onFollowUp(question)} className="focus-ring flex w-full items-center gap-2 py-2 text-left text-md text-ink-secondary transition-colors duration-fast hover:text-ink-primary">
                <Icon name="followUp" className="h-3 w-3 shrink-0 text-ink-muted" />
                {question}
              </Pressable>
            </li>
          ))}
        </ul>
      ) : null}
    </article>
    </ContextMenu>
  );
}

/** Summarizes older messages now, for the model. The chat keeps showing all of them. */
export function CompactAction({ session, wide = false }: { session: string; wide?: boolean }) {
  const toast = useToast();
  const compact = useCompactSession();
  const run = () =>
    compact.mutate(session, {
      onSuccess: (result) => toast({ title: t(result.compacted ? "chat.compact.done" : "chat.compact.nothing") }),
      onError: (error) => toast({ title: error instanceof ApiRequestError ? error.detail.message : t("chat.compact.failed") }),
    });
  if (wide) return <Button variant="quiet" loading={compact.isPending} onClick={run}>{t("chat.compact")}</Button>;
  return <IconButton icon="compact" label={t("chat.compact")} disabled={compact.isPending} onClick={run} />;
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
export function ChatView({ id, initial, active, footer }: { id: string; initial: UIMessage[]; active: boolean; footer?: React.ReactNode }) {
  const transport = useMemo(
    () =>
      new DefaultChatTransport<UIMessage>({
        api: "/api/sessions/chat",
        // The backend keeps the history, so it only needs what was just typed.
        prepareSendMessagesRequest: ({ messages, trigger }) => {
          const last = messages[messages.length - 1];
          const text = last?.parts.flatMap((part) => (part.type === "text" ? [part.text] : [])).join("\n") ?? "";
          return { body: { id, text, ...(trigger === "regenerate-message" ? { retry: true } : {}) } };
        },
      }),
    [id],
  );
  const chat = useChat({ id, transport, messages: initial, resume: active });
  const { sendMessage, setMessages, regenerate, resumeStream, messages, status } = chat;
  const stop = useStopSession();
  const session = useSession(id);
  const format = useDateTime();
  const setModel = useSetSessionModel();
  const chooseVersion = useChooseVersion();
  const context = useSessionContext(id);
  const setContext = useSetContext();
  const attached: readonly Attached[] = context.data?.items ?? [];
  const reading = useAttachedReading(attached);
  const editor = useRef<HTMLTextAreaElement>(null);
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

  // An event or the clock can start a run while this is open. It appears here as it happens.
  const { subscribe } = useEvents();
  const busy = useRef(working);
  const behind = useRef(false);
  const catchUp = useCallback(async () => {
    behind.current = false;
    const view = await query("session.get", { id });
    setMessages(view.messages as unknown as UIMessage[]);
    if (view.active) void resumeStream();
  }, [id, resumeStream, setMessages]);
  useEffect(() => {
    busy.current = working;
    if (!working && behind.current) void catchUp();
  }, [working, catchUp]);
  useEffect(
    () =>
      subscribe((event) => {
        const started = event.type === "agent.triggered" && event.payload.origin !== "person";
        if (!(started || event.type === "agent.held") || event.payload.session !== id) return;
        if (busy.current) behind.current = true;
        else void catchUp();
      }),
    [subscribe, id, catchUp],
  );

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
    if (working || reading.size) return;
    say(words);
    following.current = true;
    setText("");
  };
  // Only fills the box. Sending it is a new message, and nothing earlier changes.
  const edit = (words: string) => {
    setText(words);
    requestAnimationFrame(() => {
      editor.current?.focus();
      editor.current?.setSelectionRange(words.length, words.length);
    });
  };
  const attach = (items: readonly Attached[]) => {
    const refs = attached.map((item) => item.ref);
    setContext.mutate({ id, context: [...refs, ...items.map((item) => item.ref).filter((ref) => !refs.includes(ref))] });
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
              <UserMessage key={message.id} message={message} onEdit={edit} />
            ) : (
              <Fragment key={message.id}>
              <AssistantMessage message={message} session={id} running={working && !waiting} isLast={index === messages.length - 1} showFollowUps={index === lastAssistant && !working} onFollowUp={say} canRetry={index === lastAssistant && !working} onRetry={() => void regenerate()} onChooseVersion={(turn) => chooseVersion.mutate({ id, turn }, { onSuccess: (view) => setMessages(view.messages as unknown as UIMessage[]) })} />
                {(session.data?.compactions ?? []).filter((entry) => entry.after_turn === factsOf(message).turn).map((entry) => (
                  <WavyDivider key={entry.time}>{t("chat.compacted", { when: format(entry.time), before: tokensOf(entry.before_tokens), after: tokensOf(entry.after_tokens) })}</WavyDivider>
                ))}
              </Fragment>
            ),
          )}
          {status === "submitted" && messages[messages.length - 1]?.role === "user" ? (
            <p data-testid="thinking-start" className="flex items-center gap-2 py-1 text-md text-ink-muted">
              <Icon name="thinking" className="h-4 w-4 animate-working motion-reduce:animate-none" />
              {t("chat.thinking")}
            </p>
          ) : null}
        </div>
        <Presence>
          {away ? (
            <RiseButton
              aria-label={t("chat.toLatest")}
              onClick={() => {
                following.current = true;
                setAway(false);
                log.current?.scrollTo?.({ top: log.current.scrollHeight, behavior: "smooth" });
              }}
              className="focus-ring absolute bottom-2 left-1/2 flex h-6 w-6 -translate-x-1/2 items-center justify-center rounded-full border border-line-subtle bg-surface-raised text-ink-secondary shadow-raised"
            >
              <Icon name="moveDown" className="h-3 w-3" />
            </RiseButton>
          ) : null}
        </Presence>
      </div>
      <div className="flex flex-col gap-2 p-3">
          <AttachedChips items={attached} reading={reading} onRemove={(ref) => setContext.mutate({ id, context: attached.filter((item) => item.ref !== ref).map((item) => item.ref) })} />
        {chat.error ? <ErrorState title={t("sessions.failed")} description={chat.error.message} /> : null}
          <Composer
            value={text}
            onChange={setText}
            onSubmit={submit}
            busy={working && !asking}
            onStop={() => stop.mutate(id)}
            stopping={stop.isPending}
            disabled={deciding && !asking}
            holdSend={reading.size > 0}
            placeholder={t(asking ? "chat.placeholder.answer" : deciding ? "chat.placeholder.decide" : "sessions.prompt.placeholder")}
            label={t("sessions.prompt")}
            inputRef={editor}
            leading={<AttachMenu onAttach={attach} />}
            trailing={<ModelPicker value={session.data?.session.model ?? null} onChange={(model) => setModel.mutate({ id, model })} />}
          />
          {footer}
      </div>
    </div>
  );
}
