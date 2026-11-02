"use client";

import type { ReactNode, Ref } from "react";
import { Icon } from "@/ui/icons";
import { t } from "@/ui/strings";
import { Swap } from "@/ui/primitives/Motion";
import { BareTextarea, Pressable } from "@/ui/primitives/Pressable";

const ACTION = "flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-secondary transition-colors duration-fast hover:bg-surface-sunken hover:text-ink-primary disabled:cursor-not-allowed disabled:bg-transparent disabled:text-ink-faint";

/** Where the person writes. Enter sends and Shift+Enter starts a new line. */
export function Composer({ value, onChange, onSubmit, busy = false, onStop, stopping = false, disabled = false, holdSend = false, placeholder, label, autoFocus = false, inputRef, leading, trailing }: { value: string; onChange: (value: string) => void; onSubmit: () => void; busy?: boolean; onStop?: () => void; stopping?: boolean; disabled?: boolean; holdSend?: boolean; placeholder: string; label: string; autoFocus?: boolean; inputRef?: Ref<HTMLTextAreaElement>; leading?: ReactNode; trailing?: ReactNode }) {
  return (
    <form
      className="flex flex-col gap-1 rounded-lg border border-line-subtle bg-surface-raised p-2 shadow-raised transition-colors duration-fast focus-within:border-line-strong"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <BareTextarea
        ref={inputRef}
        aria-label={label}
        placeholder={placeholder}
        rows={2}
        value={value}
        disabled={disabled}
        // eslint-disable-next-line jsx-a11y/no-autofocus -- only when the person just opened the chat
        autoFocus={autoFocus}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            onSubmit();
          }
        }}
        className="chat-field w-full bg-transparent px-1 py-1 text-md text-ink-primary outline-none placeholder:text-ink-muted disabled:cursor-not-allowed"
      />
      <div className="flex items-center gap-1">
        {leading}
        <div className="flex min-w-0 flex-1 items-center justify-end gap-1">
          {trailing}
          <Swap value={busy}>
            {busy ? (
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
    </form>
  );
}
