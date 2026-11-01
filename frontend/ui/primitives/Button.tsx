import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";
import { Icon } from "@/ui/icons";

const VARIANTS = {
  primary: "bg-accent-default text-accent-on hover:bg-accent-hover",
  secondary: "border border-line-subtle bg-surface-raised text-ink-primary hover:bg-surface-sunken",
  quiet: "text-ink-secondary hover:bg-surface-sunken hover:text-ink-primary",
  danger: "border border-status-danger text-status-danger hover:bg-surface-sunken",
} as const;

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof VARIANTS;
  loading?: boolean;
  children: ReactNode;
  ref?: Ref<HTMLButtonElement>;
}

export function Button({ variant = "secondary", loading = false, disabled, className = "", children, ...props }: ButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`focus-ring inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-md font-medium transition-colors duration-fast active:opacity-80 disabled:cursor-not-allowed disabled:opacity-60 ${VARIANTS[variant]} ${className}`}
      {...props}
    >
      {loading ? <Icon name="loading" className="h-4 w-4 shrink-0 animate-spin" /> : null}
      {children}
    </button>
  );
}
