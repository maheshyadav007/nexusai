import type { ReactNode } from "react";
import { MailWorkspace } from "@/ui/features/mail/MailWorkspace";

export default async function Layout({ params, children }: { params: Promise<{ name: string }>; children: ReactNode }) {
  const { name } = await params;
  return (
    <MailWorkspace folder="all" location={decodeURIComponent(name)}>
      {children}
    </MailWorkspace>
  );
}
