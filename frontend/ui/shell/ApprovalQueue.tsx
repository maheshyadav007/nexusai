"use client";

import Link from "next/link";
import { useApprovals, useDecideApproval } from "@/ui/client/sessions";
import type { ToolApproval } from "@/ui/client/contracts.generated";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { Popover } from "@/ui/primitives/Popover";
import { t } from "@/ui/strings";

/** The decision itself: what would happen, why it's asking, and how to answer. */
export function ApprovalDetails({ approval }: { approval: ToolApproval }) {
  const decide = useDecideApproval();
  return (
    <div data-testid="approval" className="flex flex-col gap-2">
      <p className="break-words text-md font-medium text-ink-primary">{approval.summary}</p>
      <p className="text-sm text-ink-secondary">{approval.reason}</p>
      {approval.detail ? <pre className="max-h-popover overflow-auto whitespace-pre-wrap break-words rounded-md bg-surface-sunken p-2 font-mono text-sm text-ink-secondary">{approval.detail}</pre> : null}
      <p className="text-sm text-ink-muted">{t(approval.undoable ? "approvals.undoable" : "approvals.notUndoable")}</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" loading={decide.isPending} onClick={() => decide.mutate({ id: approval.id, choice: "once" })}>
          {t("approvals.once")}
        </Button>
        <Button disabled={decide.isPending} onClick={() => decide.mutate({ id: approval.id, choice: "session" })}>
          {t("approvals.session")}
        </Button>
        <Button variant="danger" disabled={decide.isPending} onClick={() => decide.mutate({ id: approval.id, choice: "deny" })}>
          {t("approvals.deny")}
        </Button>
      </div>
    </div>
  );
}

export function ApprovalQueue() {
  const approvals = useApprovals();
  const items = approvals.data?.approvals ?? [];
  const label = items.length ? t("approvals.count", { count: items.length }) : t("approvals.title");
  return (
    <Popover
      label={t("approvals.title")}
      trigger={
        <button type="button" aria-label={label} className="focus-ring inline-flex items-center gap-1 rounded-md p-2 text-ink-secondary transition-colors duration-fast hover:bg-surface-sunken hover:text-ink-primary">
          <Icon name="approvals" />
          {items.length ? <span className="text-sm tabular-nums text-accent-default">{items.length}</span> : null}
        </button>
      }
    >
      {items.length === 0 ? (
        <EmptyState icon="approvals" title={t("approvals.empty.title")} description={t("approvals.empty.description")} />
      ) : (
        <ul className="flex max-h-popover flex-col gap-4 overflow-y-auto">
          {items.map((approval) => (
            <li key={approval.id} className="flex flex-col gap-1">
              <Link href={`/agent/sessions/${approval.session}`} className="focus-ring truncate rounded-sm text-sm text-ink-muted underline underline-offset-2">
                {approval.session_title}
              </Link>
              <ApprovalDetails approval={approval} />
            </li>
          ))}
        </ul>
      )}
    </Popover>
  );
}
