"use client";

import { useState } from "react";
import type { ToolApproval } from "@/ui/client/contracts.generated";
import { Button } from "@/ui/primitives/Button";
import { CodeView } from "@/ui/primitives/CodeView";
import { Dialog } from "@/ui/primitives/Dialog";
import { t } from "@/ui/strings";

/** What's being approved in a line, with everything behind it formatted and a click away. */
export function ApprovalPreviewView({ approval }: { approval: ToolApproval }) {
  const [open, setOpen] = useState(false);
  const preview = approval.preview;
  const summary = preview?.summary ?? approval.summary;
  const content = preview?.content ?? approval.detail;
  // The agent's own words on why, kept apart from what the tool will actually do.
  const said = approval.summary !== summary ? approval.summary : null;
  return (
    <div className="flex flex-col gap-1">
      <p data-testid="approval-summary" className="break-words text-md font-medium text-ink-primary">{summary}</p>
      {said ? <p className="break-words text-sm text-ink-secondary">{t("approvals.agentSays", { words: said })}</p> : null}
      <p className="text-sm text-ink-muted">{approval.reason}</p>
      {content ? (
        <div>
          <Dialog title={summary} {...(preview?.location ? { description: preview.location } : {})} shape="glass" open={open} onOpenChange={setOpen} trigger={<Button variant="quiet" className="py-px">{t("approvals.viewDetails")}</Button>}>
            <div data-testid="approval-content" className="min-h-0 flex-1 overflow-auto rounded-md bg-surface-page">
              <CodeView text={content} label={summary} />
            </div>
          </Dialog>
        </div>
      ) : null}
    </div>
  );
}
