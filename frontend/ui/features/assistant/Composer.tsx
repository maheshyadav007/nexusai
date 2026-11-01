"use client";

import { Icon } from "@/ui/icons";
import { t } from "@/ui/strings";
import { Swap } from "@/ui/primitives/Motion";
import { BareTextarea, Pressable } from "@/ui/primitives/Pressable";

/** Where the person writes. Enter sends and Shift+Enter starts a new line. */
export function Composer({ value, onChange, onSubmit, busy = false, onStop, stopping = false, disabled = false, placeholder, label, autoFocus = false }: { value: string; onChange: (value: string) => void; onSubmit: () => void; busy?: boolean; onStop?: () => void; stopping?: boolean; disabled?: boolean; placeholder: string; label: string; autoFocus?: boolean }) {
  return (
    <form
      className="flex items-end gap-2 rounded-lg border border-line-subtle bg-surface-raised p-2 shadow-raised transition-colors duration-fast focus-within:border-line-strong"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <BareTextarea
        aria-label={label}
        placeholder={placeholder}
        rows={1}
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
        className="grow-field min-w-0 flex-1 resize-none bg-transparent px-1 py-1 text-md text-ink-primary outline-none placeholder:text-ink-muted disabled:cursor-not-allowed"
      />
      <Swap value={busy}>
        {busy ? (
        <Pressable aria-label={t("sessions.stop")} disabled={stopping} onClick={onStop} className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface-inverse text-ink-inverse transition-opacity duration-fast active:opacity-80">
          <Icon name="stop" className="h-3 w-3" />
        </Pressable>
        ) : (
        <Pressable type="submit" aria-label={t("sessions.send")} disabled={disabled || !value.trim()} className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accent-default text-accent-on transition-colors duration-fast hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-faint">
          <Icon name="moveUp" className="h-3 w-3" />
        </Pressable>
        )}
      </Swap>
    </form>
  );
}
