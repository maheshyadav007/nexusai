"use client";

import type { ReactNode, Ref } from "react";
import { Icon } from "@/ui/icons";
import { t } from "@/ui/strings";
import { Swap } from "@/ui/primitives/Motion";
import { BareTextarea, Pressable } from "@/ui/primitives/Pressable";
import { Mascot } from "@/ui/primitives/Mascot";
import { useAgentCards } from "@/ui/client/work";

const TYPING_HANDLE = /^@([a-z0-9-]*)$/i;

/** While the message is only "@…", the agents it could go to. Picking one fills in its handle. */
function AgentSuggestions({ value, onPick }: { value: string; onPick: (handle: string) => void }) {
  const cards = useAgentCards().data?.cards ?? [];
  const typed = TYPING_HANDLE.exec(value)?.[1]?.toLowerCase();
  if (typed === undefined) return null;
  const matches = cards.filter((card) => card.accepts.includes("person") && card.handle.startsWith(typed));
  if (!matches.length) return null;
  return (
    <ul aria-label={t("chat.agents")} className="flex flex-wrap gap-1 px-1">
      {matches.map((card) => (
        <li key={card.id}>
          <Pressable onClick={() => onPick(card.handle)} className="flex items-center gap-1 rounded-full border border-line-subtle px-2 py-px text-sm text-ink-secondary hover:border-line-strong hover:text-ink-primary">
            <Mascot seed={card.mascot.seed} shape={card.mascot.style} name={card.name} size="sm" />
            <span>{t("chat.agentChoice", { agent: card.name, handle: card.handle })}</span>
          </Pressable>
        </li>
      ))}
    </ul>
  );
}

const ACTION = "flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-secondary transition-colors duration-fast hover:bg-surface-sunken hover:text-ink-primary disabled:cursor-not-allowed disabled:bg-transparent disabled:text-ink-faint";

/** Where the person writes. Enter sends and Shift+Enter starts a new line. */
export function Composer({ value, onChange, onSubmit, busy = false, onStop, stopping = false, disabled = false, holdSend = false, placeholder, label, autoFocus = false, inputRef, leading, trailing, notice }: { value: string; onChange: (value: string) => void; onSubmit: () => void; busy?: boolean; onStop?: () => void; stopping?: boolean; disabled?: boolean; holdSend?: boolean; placeholder: string; label: string; autoFocus?: boolean; inputRef?: Ref<HTMLTextAreaElement>; leading?: ReactNode; trailing?: ReactNode; notice?: ReactNode }) {
  return (
    <form
      className="flex flex-col gap-1 rounded-lg border border-line-subtle bg-surface-raised p-2 shadow-raised transition-colors duration-fast focus-within:border-line-strong"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <AgentSuggestions value={value} onPick={(handle) => onChange(`@${handle} `)} />
      <BareTextarea
        ref={inputRef}
        aria-label={label}
        placeholder={placeholder}
        rows={2}
        value={value}
        disabled={disabled || (busy && !onStop)}
        // eslint-disable-next-line jsx-a11y/no-autofocus -- only when the person just opened the chat
        autoFocus={autoFocus}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            onSubmit();
          }
        }}
        className="chat-field w-full bg-transparent px-1 py-1 text-md text-ink-primary outline-none placeholder:text-ink-muted disabled:cursor-not-allowed disabled:opacity-50"
      />
      <div className="flex items-center gap-1">
        {leading}
        <div className="flex min-w-0 flex-1 items-center justify-end gap-1">
          {trailing}
          <Swap value={busy}>
            {busy && !onStop ? <span role="status" aria-label={t("generation.preparing")} className={ACTION}><Icon name="loading" className="h-3 w-3 animate-spin motion-reduce:animate-none" /></span> : busy ? (
              <Pressable aria-label={t("sessions.stop")} disabled={stopping} onClick={onStop} className={ACTION}>
                <Icon name="stop" className="h-3 w-3" />
              </Pressable>
            ) : (
              <Pressable type="submit" aria-label={t("sessions.send")} disabled={disabled || holdSend || !value.trim()} className={ACTION}>
                <Icon name="moveUp" className="h-4 w-4" />
              </Pressable>
            )}
          </Swap>
        </div>
      </div>
      {notice}
    </form>
  );
}
