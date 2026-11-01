import type { ButtonHTMLAttributes, InputHTMLAttributes, Ref, TextareaHTMLAttributes } from "react";

type PressableProps = ButtonHTMLAttributes<HTMLButtonElement> & { ref?: Ref<HTMLButtonElement> };

/** The door for anything clickable that isn't a Button: focus ring and press feedback live here. */
export function Pressable({ className = "", ...props }: PressableProps) {
  return <button type="button" className={`focus-ring press ${className}`} {...props} />;
}

/** A full-width row in a list. */
export function RowButton({ className = "", ...props }: PressableProps) {
  return <Pressable className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors duration-fast hover:bg-surface-sunken ${className}`} {...props} />;
}

/** A field that blends into what holds it, like the message box or a quick-add line. */
export function BareInput({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement> & { ref?: Ref<HTMLInputElement> }) {
  return <input className={`bg-transparent text-ink-primary placeholder:text-ink-muted ${className}`} {...props} />;
}

export function BareTextarea({ className = "", ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { ref?: Ref<HTMLTextAreaElement> }) {
  return <textarea className={`grow-field resize-none bg-transparent text-ink-primary placeholder:text-ink-muted ${className}`} {...props} />;
}
