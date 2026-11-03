"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { isManagedSession, useSession } from "@/ui/client/sessions";
import { CompactAction, FinalPrompt } from "@/ui/features/assistant/ChatView";
import { ChatViewActions } from "@/ui/features/assistant/ChatViewActions";
import { SessionChat } from "@/ui/features/assistant/SessionChat";
import { Icon } from "@/ui/icons";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { t } from "@/ui/strings";
import { SESSION_STATES } from "./SessionsScreen";

export function PanelEntry({ id }: { id: string | null }) {
  const assistant = useAssistant();
  const opened = useRef(false);
  useEffect(() => {
    if (opened.current || !assistant.ready) return;
    opened.current = true;
    if (id) assistant.openSession(id);
    else assistant.openDraft();
  }, [assistant, id]);
  return null;
}

export function AgentScreen({ id }: { id: string }) {
  const full = useSearchParams().get("view") === "full";
  return full ? <FullAgentScreen id={id} /> : <PanelEntry id={id} />;
}

function FullAgentScreen({ id }: { id: string }) {
  const session = useSession(id);
  const row = session.data?.session;
  const state = row ? SESSION_STATES[row.status] : undefined;
  const waiting = row?.status === "waiting";
  return (
    <div className="mx-auto flex h-full max-w-reading flex-col">
      <header className="flex flex-col gap-1 p-4 pb-2">
        <div className="flex items-center justify-between gap-3">
        <nav aria-label={t("sessions.breadcrumb")} className="flex min-w-0 items-center gap-1 text-md">
          <Link href="/agent/sessions" className="focus-ring shrink-0 rounded-sm text-ink-muted transition-colors duration-fast hover:text-ink-primary">
            {t("nav.sessions")}
          </Link>
          <Icon name="chevronRight" className="h-3 w-3 shrink-0 text-ink-faint" />
          <h1 className="min-w-0 truncate font-medium text-ink-primary">{row?.title ?? ""}</h1>
          {state ? (
            <p role="status" data-testid="session-status" className={`ml-2 flex shrink-0 items-center gap-1 text-sm ${waiting ? "font-medium text-accent-default" : "text-ink-muted"}`}>
              <StatusDot tone={state.tone} />
              {t(state.label)}
            </p>
          ) : null}
        </nav>
        <div className="flex shrink-0 items-center gap-1">
          {row && !isManagedSession(row) ? <CompactAction session={id} wide /> : null}
          <FinalPrompt session={id} />
          <ChatViewActions session={id} full />
        </div>
        </div>
        {row?.untrusted ? <p className="text-sm text-ink-muted">{t("sessions.untrusted")}</p> : null}
      </header>
      <SessionChat key={id} id={id} />
    </div>
  );
}
