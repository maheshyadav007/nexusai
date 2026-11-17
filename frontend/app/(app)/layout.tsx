import type { ReactNode } from "react";
import { AgentToasts } from "@/ui/features/assistant/AgentToasts";
import { AssistantDock, AssistantRoom } from "@/ui/features/assistant/AssistantDock";
import { AssistantProvider } from "@/ui/features/assistant/AssistantProvider";
import { SourcePreviewProvider } from "@/ui/features/sources/SourcePreviewProvider";
import { SearchBox } from "@/ui/features/search/SearchBox";
import { AppGate } from "@/ui/shell/AppGate";
import { AppShell } from "@/ui/shell/AppShell";

export default function AppLayout({ children, modal }: { children: ReactNode; modal: ReactNode }) {
  return (
    <AppGate>
      <AssistantProvider>
        <SourcePreviewProvider>
          <AppShell room={<AssistantRoom />} search={<SearchBox />}>{children}</AppShell>
          {modal}
          <AgentToasts />
          <AssistantDock />
        </SourcePreviewProvider>
      </AssistantProvider>
    </AppGate>
  );
}
