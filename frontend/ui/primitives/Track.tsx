"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";
import { Tooltip } from "./Tooltip";

export type MarkShape = "dot" | "ring" | "diamond" | "diamondRing";
export type MarkTone = "ink" | "accent" | "warning" | "danger" | "success";

const clamp = (value: number) => `${Math.min(Math.max(value, 0), 1) * 100}%`;

/** Places an element along its track by where it falls: 0 is the start, 1 the end. Positions are
 * CSS variables, so the look stays in the theme and only the numbers come from data. */
function usePlace<T extends HTMLElement>(values: Readonly<Record<string, number>>) {
  const ref = useRef<T>(null);
  const key = JSON.stringify(values);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    for (const [name, value] of Object.entries(JSON.parse(key) as Record<string, number>)) node.style.setProperty(`--nx-${name}`, clamp(value));
  }, [key]);
  return ref;
}

const TONES: Record<MarkTone, { fill: string; ring: string }> = {
  ink: { fill: "bg-ink-secondary", ring: "border-ink-secondary" },
  accent: { fill: "bg-accent-default", ring: "border-accent-default" },
  warning: { fill: "bg-status-warning", ring: "border-status-warning" },
  danger: { fill: "bg-status-danger", ring: "border-status-danger" },
  success: { fill: "bg-status-success", ring: "border-status-success" },
};

/** The look of a mark on its own, for a key that explains a track. */
export function MarkGlyph({ shape, tone }: { shape: MarkShape; tone: MarkTone }) {
  const colors = TONES[tone];
  const diamond = shape === "diamond" || shape === "diamondRing";
  const filled = shape === "dot" || shape === "diamond";
  return <span aria-hidden className={`block h-3 w-3 shrink-0 ${diamond ? "rotate-45 scale-75" : "rounded-full"} ${filled ? colors.fill : `border-2 bg-surface-raised ${colors.ring}`}`} />;
}

/** One event on a track, with what it was in a tooltip and for screen readers. */
export function TrackMark({ at, shape, tone, label }: { at: number; shape: MarkShape; tone: MarkTone; label: string }) {
  const ref = usePlace<HTMLSpanElement>({ at });
  return (
    <Tooltip content={label}>
      <span ref={ref} role="img" aria-label={label} tabIndex={0} className="nx-track-at focus-ring rounded-full p-1">
        <MarkGlyph shape={shape} tone={tone} />
      </span>
    </Tooltip>
  );
}

/** The stretch between two points: how long something has been going on. */
export function TrackSpan({ from, to, strong = false }: { from: number; to: number; strong?: boolean }) {
  const ref = usePlace<HTMLSpanElement>({ from, width: Math.max(to - from, 0) });
  return <span ref={ref} aria-hidden className={`nx-track-span ${strong ? "bg-accent-default opacity-40" : "bg-line-subtle"}`} />;
}

/** Now, as a line down the track. */
export function TrackNow({ at }: { at: number }) {
  const ref = usePlace<HTMLSpanElement>({ at });
  return <span ref={ref} aria-hidden className="nx-track-now bg-accent-default" />;
}

/** A line along which marks are placed. */
export function Track({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`relative block h-7 ${className}`}>{children}</span>;
}
