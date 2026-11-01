import type { ReactNode } from "react";
import { MailWorkspace } from "@/ui/features/mail/MailWorkspace";

export default async function Layout({ params, children }: { params: Promise<{ folder: string }>; children: ReactNode }) {
  const { folder } = await params;
  return <MailWorkspace folder={folder}>{children}</MailWorkspace>;
}
