"use client";

import { CheckCheck, Eye, MailOpen, Radio, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PriorityBadge } from "@/components/work/priority-badge";
import type { ClassifiedEmail } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ClassifiedEmailCard({
  email,
  selected,
  onSelect,
  onToggleRead
}: {
  email: ClassifiedEmail;
  selected: boolean;
  onSelect: () => void;
  onToggleRead: () => void;
}) {
  return (
    <article
      className={cn(
        "rounded-xl border bg-surface-1 p-md transition duration-200 ease-product hover:border-hairline-strong hover:bg-surface-2",
        selected ? "border-accent shadow-focus" : "border-hairline shadow-panel"
      )}
    >
      <button type="button" onClick={onSelect} className="w-full text-left">
        <div className="mb-sm flex items-start justify-between gap-md">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-xs">
              <span className="text-small text-ink">{email.sender}</span>
              <span className="text-caption text-ink-tertiary">{email.senderRole}</span>
              {!email.read ? <span className="size-xs rounded-full bg-accent" /> : null}
            </div>
            <h3 className="mt-xs text-heading text-ink">{email.subject}</h3>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-xs">
            <PriorityBadge priority={email.priority} />
            <span className="text-caption text-ink-tertiary">{email.received}</span>
          </div>
        </div>
        <p className="line-clamp-2 text-small text-ink-subtle">{email.summary}</p>
        <div className="mt-md flex flex-wrap items-center gap-xs">
          <Badge variant={email.read ? "default" : "running"}>{email.read ? "read" : "unread"}</Badge>
          <span className="inline-flex min-w-0 items-center gap-xxs text-caption text-ink-tertiary">
            <Sparkles className="size-sm shrink-0 text-accent" />
            <span className="truncate">{email.suggestedAction}</span>
          </span>
        </div>
      </button>

      <div className="mt-md flex flex-wrap gap-xs border-t border-hairline pt-sm">
        <Button size="sm" variant="secondary" onClick={onSelect}>
          <Eye className="size-sm" />
          Inspect
        </Button>
        <Button size="sm" variant="ghost" onClick={onToggleRead}>
          {email.read ? <Radio className="size-sm" /> : <CheckCheck className="size-sm" />}
          {email.read ? "Mark unread" : "Mark read"}
        </Button>
        <Button size="sm" variant="ghost">
          <MailOpen className="size-sm" />
          Open email
        </Button>
      </div>
    </article>
  );
}
