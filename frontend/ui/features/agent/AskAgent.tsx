"use client";

import { useRouter } from "next/navigation";
import type { CreateSession } from "@/ui/client/contracts.generated";
import { useCreateSession } from "@/ui/client/sessions";
import { Button } from "@/ui/primitives/Button";
import { t } from "@/ui/strings";

/** Opens a session with this item attached. The person can see it and remove it there. */
export function AskAgent({ context, title, label }: { context: string[]; title?: string; label?: string }) {
  const router = useRouter();
  const create = useCreateSession();
  return (
    <Button loading={create.isPending} onClick={() => create.mutate({ context: context as CreateSession["context"], ...(title ? { title } : {}) }, { onSuccess: (session) => router.push(`/agent/sessions/${session.id}`) })}>
      {label ?? t("agent.ask")}
    </Button>
  );
}
