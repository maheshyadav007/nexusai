import type { ReactNode } from "react";

const TONES = {
  neutral: "text-ink-secondary",
  accent: "text-accent-default",
  success: "text-status-success",
  warning: "text-status-warning",
  danger: "text-status-danger",
} as const;

export function Badge({ tone = "neutral", children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-sm bg-surface-sunken px-2 text-sm tabular-nums ${TONES[tone]}`}>{children}</span>;
}
