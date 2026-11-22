"use client";

import { useWaitingCount } from "@/ui/client/work";
import { Icon } from "@/ui/icons";
import { AttentionCount } from "@/ui/primitives/AttentionCount";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { Popover } from "@/ui/primitives/Popover";
import { Pressable } from "@/ui/primitives/Pressable";
import { t } from "@/ui/strings";
import { WaitingOnYou } from "./TodayScreen";

/** The shield in the top bar: everything waiting for the person, the same as "For your
 *  decision" on Today, and answered right here. An agent's question counts as much as an
 *  approval does. */
export function WaitingInbox() {
  const count = useWaitingCount();
  const label = count ? t("waiting.count", { count }) : t("waiting.title");
  return (
    <Popover
      label={t("waiting.title")}
      size="panel"
      trigger={
        <Pressable aria-label={label} data-testid="waiting-inbox" className="inline-flex items-center gap-1 rounded-md p-2 text-ink-secondary transition-colors duration-fast hover:bg-surface-sunken hover:text-ink-primary">
          <Icon name="approvals" />
          {count ? <AttentionCount value={count} /> : null}
        </Pressable>
      }
    >
      {count ? <WaitingOnYou inPopover /> : <EmptyState icon="approvals" title={t("waiting.empty.title")} description={t("waiting.empty.description")} />}
    </Popover>
  );
}
