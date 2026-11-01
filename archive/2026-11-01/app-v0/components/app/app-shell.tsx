"use client";

import { AppHeader } from "@/components/app/app-header";
import { ClassificationSidebar } from "@/components/app/classification-sidebar";
import { EmailChatRail } from "@/components/app/email-chat-rail";
import { NotificationCenter } from "@/components/app/notification-center";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen overflow-hidden bg-canvas text-ink">
      <AppHeader />
      <div className="app-shell-grid">
        <ClassificationSidebar />
        <main className="relative h-[calc(100vh-var(--layout-topbar))] min-w-0 overflow-y-auto border-x border-hairline bg-canvas-elevated/50">
          {children}
        </main>
        <EmailChatRail />
      </div>
      <NotificationCenter />
    </div>
  );
}
