"use client";

import Link from "next/link";
import { Icon } from "@/ui/icons";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useDismissChecklist, useOnboarding } from "@/ui/client/onboarding";
import { useMailStatus } from "@/ui/client/mail";
import { useModelStatus } from "@/ui/client/models";
import { Button } from "@/ui/primitives/Button";
import { t, type StringKey } from "@/ui/strings";

export function PostyGuide({ message, children }: { message: StringKey; children?: React.ReactNode }) {
  const text = t(message);
  const [shown, setShown] = useState(text);
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reduce.matches) { setShown(text); return; }
    setShown(""); let length = 0;
    const timer = setInterval(() => { length = Math.min(text.length, length + 4); setShown(text.slice(0, length)); if (length === text.length) clearInterval(timer); }, 24);
    return () => clearInterval(timer);
  }, [text]);
  return <aside data-testid="posty-guide" aria-label={t("posty.guide")} className="flex items-start gap-4 py-2">
    <span aria-hidden="true" className="flex h-rail w-rail shrink-0 items-center justify-center text-accent-default"><Icon name="agent" className="h-rail w-rail" /></span>
    <div className="min-w-0 flex-1"><p className="text-lg font-medium text-accent-default">{t("posty.name")}</p><p className="mt-1 text-lg text-ink-primary"><span aria-hidden="true">{shown || "\u00a0"}</span><span className="sr-only">{text}</span></p>{children ? <div className="mt-3 flex flex-wrap items-center gap-3">{children}</div> : null}</div>
  </aside>;
}

const ROUTES: readonly [string, StringKey][] = [
  ["/mail", "posty.page.mail"], ["/connectors", "posty.page.connectors"], ["/settings", "posty.page.settings"],
  ["/documents", "posty.page.documents"], ["/planner", "posty.page.planner"], ["/agent", "posty.page.agents"],
  ["/search", "posty.page.search"], ["/cockpit", "posty.page.cockpit"],
];
export function WorkspaceGuide() {
  const onboarding = useOnboarding(); const dismiss = useDismissChecklist();
  const mail = useMailStatus(); const model = useModelStatus(); const path = usePathname();
  if (!onboarding.data || onboarding.data.checklist_dismissed) return null;
  const message = ROUTES.find(([prefix]) => path.startsWith(prefix))?.[1] ?? "posty.page.today";
  const destination = !mail.data?.account ? "/connectors" : !model.data?.connected ? "/settings?section=models" : "/mail/inbox";
  return <div className="mx-auto w-full max-w-content px-5 pt-4"><PostyGuide message={message}><Link href={destination} className="focus-ring text-sm text-accent-default underline">{t("posty.next")}</Link><Button variant="quiet" onClick={() => dismiss.mutate(undefined)}>{t("posty.dismiss")}</Button></PostyGuide></div>;
}
