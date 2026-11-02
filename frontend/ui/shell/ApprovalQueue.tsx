"use client";

import Link from "next/link";
import { groupApprovals, useApprovals, useDecideApproval, useDecideApprovals } from "@/ui/client/sessions";
import type { ToolApproval } from "@/ui/client/contracts.generated";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { Popover } from "@/ui/primitives/Popover";
import { Pressable } from "@/ui/primitives/Pressable";
import { ApprovalPreviewView } from "./ApprovalPreviewView";
import { t, tn } from "@/ui/strings";

/** The decision itself: what would happen, why it's asking, and how to answer. */
export function ApprovalDetails({ approval }: { approval: ToolApproval }) {
  const decide = useDecideApproval();
  return (
    <div data-testid="approval" className="flex flex-col gap-2">
      <ApprovalPreviewView approval={approval} />
      <p className="text-sm text-ink-muted">{t(approval.undoable ? "approvals.undoable" : "approvals.notUndoable")}</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" loading={decide.isPending} onClick={() => decide.mutate({ id: approval.id, choice: "once" })}>
          {t("approvals.once")}
        </Button>
        {approval.can_remember ? (
          <Button disabled={decide.isPending} onClick={() => decide.mutate({ id: approval.id, choice: "session" })}>
            {t("approvals.session")}
          </Button>
        ) : null}
        <Button variant="danger" disabled={decide.isPending} onClick={() => decide.mutate({ id: approval.id, choice: "deny" })}>
          {t("approvals.deny")}
        </Button>
      </div>
    </div>
  );
}

function GroupDecision({ group }: { group: readonly ToolApproval[] }) {
  const decide = useDecideApprovals();
  const ids = group.map((item) => item.id);
  const first = group[0];
  return (
    <div data-testid="approval" className="flex flex-col gap-2">
      <p className="text-md font-medium text-ink-primary">{tn("approvals.group", group.length, { label: first?.tool_label ?? "" })}</p>
      <p className="text-sm text-ink-secondary">{first?.reason}</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" loading={decide.isPending} onClick={() => decide.mutate({ allow: ids })}>
          {t("approvals.allowCount", { count: ids.length })}
        </Button>
        {first?.can_remember ? (
          <Button disabled={decide.isPending} onClick={() => decide.mutate({ allow: ids, remember: true })}>
            {t("approvals.session")}
          </Button>
        ) : null}
        <Button variant="quiet" disabled={decide.isPending} onClick={() => decide.mutate({ deny: ids })}>
          {t("approvals.denyAll")}
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
        <Pressable aria-label={label} className="inline-flex items-center gap-1 rounded-md p-2 text-ink-secondary transition-colors duration-fast hover:bg-surface-sunken hover:text-ink-primary">
          <Icon name="approvals" />
          {items.length ? <span className="text-sm tabular-nums text-accent-default">{items.length}</span> : null}
        </Pressable>
      }
    >
      {items.length === 0 ? (
        <EmptyState icon="approvals" title={t("approvals.empty.title")} description={t("approvals.empty.description")} />
      ) : (
        <ul className="flex max-h-popover flex-col gap-4 overflow-y-auto">
          {groupApprovals(items).map((group) => {
            const first = group[0];
            if (!first) return null;
            return (
              <li key={`${first.session}-${first.tool}`} className="flex flex-col gap-1">
                <Link href={`/agent/sessions/${first.session}`} className="focus-ring truncate rounded-sm text-sm text-ink-muted underline underline-offset-2">
                  {first.session_title}
                </Link>
                {group.length === 1 ? <ApprovalDetails approval={first} /> : <GroupDecision group={group} />}
              </li>
            );
          })}
        </ul>
      )}
    </Popover>
  );
}
