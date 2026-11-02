"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState, type ButtonHTMLAttributes, type ComponentProps, type HTMLAttributes, type ReactNode } from "react";
import type { Ref } from "react";
import { QUICK, readSpace, SMOOTH, SLOW } from "./motionValues";

export { readSpace } from "./motionValues";

/**
 * The only door to animation. Screens name what's happening (something appeared, opened, changed)
 * and this file decides how it moves, so changing how the app feels means editing one place.
 */

const RISE = { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0, y: 8 } };
// Between things that arrive one after another, in seconds.
const SEQUENCE_GAP = 0.32;
const STILL = { duration: 0 };

/** How long things take. Someone who asked for less motion gets none, including fades. */
export function useFeel() {
  const still = useReducedMotion();
  return still ? { quick: STILL, smooth: STILL, slow: STILL, gap: 0 } : { quick: QUICK, smooth: SMOOTH, slow: SLOW, gap: SEQUENCE_GAP };
}

type RiseTag = "div" | "li" | "article" | "section";

/** Keeps what's leaving on screen until it has finished moving. */
export function Presence({ children, onFirstRender = false }: { children: ReactNode; onFirstRender?: boolean }) {
  return <AnimatePresence initial={onFirstRender}>{children}</AnimatePresence>;
}

/** Something arriving: a message, a card, a row. `settle` slides the others out of its way, and `delay` is its place in a sequence. */
export function Rise({ as = "div", settle, delay = 0, ...props }: { as?: RiseTag; settle?: boolean | "position"; delay?: number } & HTMLAttributes<HTMLElement>) {
  const feel = useFeel();
  const Tag = motion[as] as typeof motion.div;
  return <Tag {...RISE} transition={{ ...feel.smooth, delay: delay * feel.gap }} {...(settle ? { layout: settle } : {})} {...(props as ComponentProps<typeof motion.div>)} />;
}

/** A button that comes and goes, such as the jump to the latest message. */
export function RiseButton(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  const feel = useFeel();
  return <motion.button type="button" {...RISE} transition={feel.quick} {...(props as ComponentProps<typeof motion.button>)} />;
}

/** More detail opening in place. */
export function Reveal({ open, children }: { open: boolean; children: ReactNode }) {
  const feel = useFeel();
  return (
    <AnimatePresence initial={false}>
      {open ? (
        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={feel.smooth} className="overflow-hidden">
          {children}
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

/** The arrow on anything that opens. */
export function Turn({ open, children }: { open: boolean; children: ReactNode }) {
  const feel = useFeel();
  return (
    <motion.span initial={false} animate={{ rotate: open ? 90 : 0 }} transition={feel.quick} className="inline-flex">
      {children}
    </motion.span>
  );
}

/** The highlight behind what's selected. It glides from the last one to this one. */
export function ActiveMark({ group, className = "absolute inset-0 rounded-md bg-surface-sunken" }: { group: string; className?: string }) {
  const feel = useFeel();
  return <motion.span layoutId={group} transition={feel.smooth} className={className} />;
}

/** A word or icon that changes in place, so the change is seen rather than just happening. */
export function Swap({ value, children, className = "inline-flex" }: { value: string | number | boolean; children: ReactNode; className?: string }) {
  const feel = useFeel();
  return (
    <AnimatePresence initial={false} mode="popLayout">
      <motion.span key={String(value)} initial={{ opacity: 0, y: 4, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -4, scale: 0.96 }} transition={feel.quick} className={className}>
        {children}
      </motion.span>
    </AnimatePresence>
  );
}

/** A count. It gives a small pop when the number changes, and not when the page first draws. */
export function CountPop({ value, className = "" }: { value: number; className?: string }) {
  const feel = useFeel();
  const seen = useRef(value);
  const changed = seen.current !== value;
  useEffect(() => {
    seen.current = value;
  }, [value]);
  return (
    <motion.span key={value} initial={changed ? { scale: 0.7, opacity: 0.4 } : false} animate={{ scale: 1, opacity: 1 }} transition={feel.quick} className={`inline-block tabular-nums ${className}`}>
      {value}
    </motion.span>
  );
}

/** A tick landing in its box. */
export function Tick({ children }: { children: ReactNode }) {
  const feel = useFeel();
  return (
    <motion.span initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={feel.quick} className="inline-flex">
      {children}
    </motion.span>
  );
}

/** A card whose content changes size. It eases to the new height instead of jumping. */
export function Grow({ children }: { children: ReactNode }) {
  const feel = useFeel();
  const inner = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number | "auto">("auto");
  useEffect(() => {
    const element = inner.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setHeight(element.offsetHeight));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return (
    <motion.div initial={false} animate={{ height }} transition={feel.smooth} className="overflow-hidden">
      <div ref={inner}>{children}</div>
    </motion.div>
  );
}

/** Pages side by side. Moving forward slides left, and going back slides right. */
export function Steps({ step, forward, children }: { step: string; forward: boolean; children: ReactNode }) {
  const feel = useFeel();
  const offset = forward ? 24 : -24;
  return (
    <AnimatePresence initial={false} mode="wait">
      <motion.div key={step} initial={{ opacity: 0, x: offset }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -offset }} transition={feel.smooth}>
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

/** A new screen arriving. */
export function PageEnter({ children }: { children: ReactNode }) {
  const feel = useFeel();
  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={feel.smooth} className="h-full">
      {children}
    </motion.div>
  );
}

/** Space opening beside the page, in time with what slides into it. */
export function Room({ width }: { width: string | null }) {
  const feel = useFeel();
  return <motion.div aria-hidden initial={false} animate={{ width: width ? readSpace(width) : 0 }} transition={feel.smooth} className="shrink-0" />;
}

/** The one panel that either floats or sits against the edge, and moves between the two. */
export function SlidePanel({ attached, place, ...props }: { attached: boolean; place: { top: number; right: number; bottom: number; borderRadius: number } } & HTMLAttributes<HTMLElement> & { ref?: Ref<HTMLElement> }) {
  const feel = useFeel();
  const away = { opacity: 0, x: attached ? 32 : 0, y: attached ? 0 : 12 };
  return <motion.section initial={{ ...away, ...place }} animate={{ opacity: 1, x: 0, y: 0, ...place }} exit={away} transition={feel.slow} {...(props as ComponentProps<typeof motion.section>)} />;
}
