import type { ReactNode } from "react";
import { AgentToasts } from "@/ui/features/assistant/AgentToasts";
import { AssistantDock } from "@/ui/features/assistant/AssistantDock";
import { AssistantProvider } from "@/ui/features/assistant/AssistantProvider";
import { AppGate } from "@/ui/shell/AppGate";
import { AppShell } from "@/ui/shell/AppShell";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AppGate>
      <AssistantProvider>
        <AppShell>{children}</AppShell>
        <AgentToasts />
        <AssistantDock />
      </AssistantProvider>
    </AppGate>
  );
}
