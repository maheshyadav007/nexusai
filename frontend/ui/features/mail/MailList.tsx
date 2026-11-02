"use client";

import { useMailStatus } from "@/ui/client/mail";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { OfflineNotice } from "@/ui/primitives/OfflineNotice";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { TextLink } from "@/ui/primitives/TextLink";
import { t } from "@/ui/strings";

export function SyncNotice() {
  const status = useMailStatus();
  const state = status.data?.state;
  if (state === "offline" || state === "failed") {
    return <OfflineNotice message={status.data?.message ?? t("mail.sync.offline")} />;
  }
  if (state === "connecting" || state === "syncing" || state === "backfilling") {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-ink-muted">
        <StatusDot tone="running" />
        {t(state === "backfilling" ? "mail.sync.backfilling" : "mail.sync.syncing")}
      </p>
    );
  }
  return null;
}

export function NoAccount() {
  return <EmptyState icon="inbox" title={t("mail.noAccount.title")} description={t("mail.noAccount.description")} action={<TextLink href="/connectors">{t("mail.noAccount.action")}</TextLink>} />;
}
