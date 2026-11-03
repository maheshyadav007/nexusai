"use client";

import { useSearchParams } from "next/navigation";
import { PanelEntry } from "./AgentScreen";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { NewChat } from "@/ui/features/assistant/AssistantDock";
import { ChatViewActions } from "@/ui/features/assistant/ChatViewActions";
import { t } from "@/ui/strings";

export function NewSessionScreen() {
  const assistant = useAssistant();
  const full = useSearchParams().get("view") === "full";
  if (!full) return <PanelEntry id={null} />;
  return <div className="mx-auto flex h-full max-w-reading flex-col">
    <header className="flex items-center justify-between border-b border-line-subtle p-4"><h1 className="text-lg font-medium text-ink-primary">{t("chat.new")}</h1><ChatViewActions session={null} full /></header>
    <NewChat key={assistant.draftRevision} />
    {assistant.startError ? <div className="p-3"><ErrorState title={t("sessions.failed")} description={assistant.startError} /></div> : null}
  </div>;
}
