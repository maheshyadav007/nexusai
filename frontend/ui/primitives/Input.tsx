"use client";

import { useState } from "react";
import { Icon } from "@/ui/icons";
import { t } from "@/ui/strings";
import type { InputHTMLAttributes, Ref, TextareaHTMLAttributes } from "react";

export const controlClass = (invalid: boolean) =>
  `focus-ring w-full rounded-md border bg-surface-raised px-3 py-2 text-md text-ink-primary transition-colors duration-fast placeholder:text-ink-muted disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted ${invalid ? "border-status-danger" : "border-line-strong"}`;

export function Input({ invalid = false, className = "", ...props }: InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean; ref?: Ref<HTMLInputElement> }) {
  const [visible, setVisible] = useState(false);
  if (props.type !== "password") return <input aria-invalid={invalid || undefined} className={`${controlClass(invalid)} ${className}`} {...props} />;
  return <span className="relative block w-full">
    <input aria-invalid={invalid || undefined} className={`${controlClass(invalid)} pr-10 ${className}`} {...props} type={visible ? "text" : "password"} />
    <button type="button" aria-label={t(visible ? "password.hide" : "password.show")} aria-pressed={visible} disabled={props.disabled} onClick={() => setVisible(value => !value)} className="focus-ring absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-md text-ink-muted"><Icon name={visible ? "eyeOff" : "eye"} /></button>
  </span>;
}

export function Textarea({ invalid = false, className = "", ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean; ref?: Ref<HTMLTextAreaElement> }) {
  return <textarea aria-invalid={invalid || undefined} className={`${controlClass(invalid)} ${className}`} {...props} />;
}
