import type { ReactNode } from "react";
import { AgentToasts } from "@/ui/features/assistant/AgentToasts";
import { AssistantDock, AssistantRoom } from "@/ui/features/assistant/AssistantDock";
import { AssistantProvider } from "@/ui/features/assistant/AssistantProvider";
import { HideFromAiProvider } from "@/ui/features/mail/HideFromAi";
import { SourcePreviewProvider } from "@/ui/features/sources/SourcePreviewProvider";
import { SearchBox } from "@/ui/features/search/SearchBox";
import { WaitingInbox } from "@/ui/features/today/WaitingInbox";
import { AppGate } from "@/ui/shell/AppGate";
import { AppShell } from "@/ui/shell/AppShell";

export default function AppLayout({ children, modal }: { children: ReactNode; modal: ReactNode }) {
  return (
    <AppGate>
      <AssistantProvider>
        <SourcePreviewProvider>
          <HideFromAiProvider>
            <AppShell room={<AssistantRoom />} search={<SearchBox />} waiting={<WaitingInbox />}>{children}</AppShell>
            {modal}
            <AgentToasts />
            <AssistantDock />
          </HideFromAiProvider>
        </SourcePreviewProvider>
      </AssistantProvider>
    </AppGate>
  );
}
