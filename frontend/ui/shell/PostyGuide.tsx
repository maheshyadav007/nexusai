"use client";

import { Icon } from "@/ui/icons";
import { useEffect, useState } from "react";
import { t, type StringKey } from "@/ui/strings";

export function PostyGuide({ message, title, prominent = false, children }: { message: StringKey; title?: string; prominent?: boolean; children?: React.ReactNode }) {
  const text = t(message);
  const [shown, setShown] = useState(text);
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reduce.matches) { setShown(text); return; }
    setShown(""); let length = 0;
    const timer = setInterval(() => { length = Math.min(text.length, length + 4); setShown(text.slice(0, length)); if (length === text.length) clearInterval(timer); }, 24);
    return () => clearInterval(timer);
  }, [text]);
  return <aside data-testid="posty-guide" aria-label={t("posty.guide")} className={prominent ? "flex flex-col items-start py-2" : "flex items-start gap-4 py-2"}>
    <span aria-hidden="true" className={`flex shrink-0 items-center justify-center text-accent-default ${prominent ? "mb-5 h-posty w-posty" : "h-rail w-rail"}`}><Icon name="agent" className={prominent ? "h-posty w-posty" : "h-rail w-rail"} /></span>
    <div className="min-w-0 flex-1">
      <p className={prominent ? "text-sm font-medium tracking-wide text-accent-default" : "text-lg font-medium text-accent-default"}>{t("posty.name")}</p>
      {title ? <h1 className="mt-3 max-w-popover text-balance font-serif text-display leading-tight text-ink-primary">{title}</h1> : null}
      <p className={`${title ? "mt-4" : "mt-1"} ${prominent ? "max-w-popover text-md leading-relaxed text-ink-secondary" : "text-lg text-ink-primary"}`}><span aria-hidden="true">{shown || "\u00a0"}</span><span className="sr-only">{text}</span></p>
      {children ? <div className="mt-4 flex flex-wrap items-center gap-3">{children}</div> : null}
    </div>
  </aside>;
}
