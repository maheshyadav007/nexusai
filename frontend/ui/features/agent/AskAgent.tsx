"use client";

import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { Button } from "@/ui/primitives/Button";
import { t } from "@/ui/strings";

/** Opens the chat with this item attached. The person can see it and remove it there. */
export function AskAgent({ context, title, label, text }: { context: string[]; title?: string; label?: string; text?: string; quiet?: boolean }) {
  const assistant = useAssistant();
  return (
    <Button variant="ai" thinking loading={assistant.starting} onClick={() => assistant.start({ context, ...(title ? { title } : {}), ...(text ? { text } : {}) })}>
      {label ?? t("agent.ask")}
    </Button>
  );
}
