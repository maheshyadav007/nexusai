import type { ReactNode } from "react";
import { AppGate } from "@/ui/shell/AppGate";
import { AppShell } from "@/ui/shell/AppShell";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AppGate>
      <AppShell>{children}</AppShell>
    </AppGate>
  );
}
