import type { InputHTMLAttributes, Ref, TextareaHTMLAttributes } from "react";

export const controlClass = (invalid: boolean) =>
  `focus-ring w-full rounded-md border bg-surface-raised px-3 py-2 text-md text-ink-primary transition-colors duration-fast placeholder:text-ink-muted disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted ${invalid ? "border-status-danger" : "border-line-strong"}`;

export function Input({ invalid = false, className = "", ...props }: InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean; ref?: Ref<HTMLInputElement> }) {
  return <input aria-invalid={invalid || undefined} className={`${controlClass(invalid)} ${className}`} {...props} />;
}

export function Textarea({ invalid = false, className = "", ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean; ref?: Ref<HTMLTextAreaElement> }) {
  return <textarea aria-invalid={invalid || undefined} className={`${controlClass(invalid)} ${className}`} {...props} />;
}
