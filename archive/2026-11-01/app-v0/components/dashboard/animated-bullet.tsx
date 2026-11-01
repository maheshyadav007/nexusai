"use client";

import { useEffect, useRef, useState } from "react";

export function AnimatedBullet({
  text,
  replacement,
  delay = 5200
}: {
  text: string;
  replacement: string;
  delay?: number;
}) {
  const [display, setDisplay] = useState(text);
  const current = useRef(text);
  const target = useRef(replacement);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    current.current = text;
    target.current = replacement;
    setDisplay(text);
  }, [replacement, text]);

  useEffect(() => {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return;

    const clear = () => {
      timers.current.forEach((timer) => window.clearTimeout(timer));
      timers.current = [];
    };

    const cycle = () => {
      clear();
      const from = current.current;
      const next = target.current;

      for (let index = from.length; index >= 0; index -= 1) {
        timers.current.push(
          window.setTimeout(() => {
            setDisplay(from.slice(0, index));
          }, (from.length - index) * 16)
        );
      }

      const typeStart = from.length * 16 + 180;
      for (let index = 0; index <= next.length; index += 1) {
        timers.current.push(
          window.setTimeout(() => {
            setDisplay(next.slice(0, index));
            if (index === next.length) {
              current.current = next;
              target.current = from;
            }
          }, typeStart + index * 18)
        );
      }
    };

    const interval = window.setInterval(cycle, delay);
    return () => {
      window.clearInterval(interval);
      clear();
    };
  }, [delay]);

  return <span>{display}</span>;
}
