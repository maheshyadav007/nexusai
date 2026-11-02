import type { ReactNode } from "react";
import { AgentToasts } from "@/ui/features/assistant/AgentToasts";
import { AssistantDock, AssistantRoom } from "@/ui/features/assistant/AssistantDock";
import { AssistantProvider } from "@/ui/features/assistant/AssistantProvider";
import { DocumentPreviewProvider } from "@/ui/features/documents/DocumentPreview";
import { SearchBox } from "@/ui/features/search/SearchBox";
import { AppGate } from "@/ui/shell/AppGate";
import { AppShell } from "@/ui/shell/AppShell";

export default function AppLayout({ children, modal }: { children: ReactNode; modal: ReactNode }) {
  return (
    <AppGate>
      <AssistantProvider>
        <DocumentPreviewProvider>
          <AppShell room={<AssistantRoom />} search={<SearchBox />}>{children}</AppShell>
          {modal}
          <AgentToasts />
          <AssistantDock />
        </DocumentPreviewProvider>
      </AssistantProvider>
    </AppGate>
  );
}
