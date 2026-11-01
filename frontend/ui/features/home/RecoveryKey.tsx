"use client";

import { useState } from "react";
import { useConfirmRecoveryKey, useNewRecoveryKey, useRecoveryKey } from "@/ui/client/home";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { Dialog } from "@/ui/primitives/Dialog";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";

/** Shows a key until the person says it's saved. After that it can't be shown again. */
export function PendingRecoveryKey({ value, action, onSaved }: { value: string; action: string; onSaved?: () => void }) {
  const toast = useToast();
  const confirm = useConfirmRecoveryKey();
  const [saved, setSaved] = useState(false);
  return (
    <div className="flex flex-col items-start gap-3">
      <p data-testid="recovery-key" className="w-full break-all rounded-md bg-surface-sunken p-3 font-mono text-lg tabular-nums text-ink-primary">
        {value}
      </p>
      <Button onClick={() => void navigator.clipboard.writeText(value).then(() => toast({ title: t("recovery.copied") }))}>{t("recovery.copy")}</Button>
      <p className="text-md text-ink-secondary">{t("recovery.warning")}</p>
      <Checkbox label={t("recovery.saved")} checked={saved} onChange={setSaved} />
      <Button variant="primary" disabled={!saved} loading={confirm.isPending} onClick={() => confirm.mutate(undefined, onSaved ? { onSuccess: onSaved } : {})}>
        {action}
      </Button>
      {confirm.isError ? <ErrorState title={t("recovery.error")} /> : null}
    </div>
  );
}

export function RecoverySettings() {
  const pending = useRecoveryKey();
  const replace = useNewRecoveryKey();
  const [asking, setAsking] = useState(false);
  if (pending.isPending) return <Skeleton className="h-6 w-full" />;
  if (pending.isError) return <ErrorState title={t("recovery.error")} onRetry={() => void pending.refetch()} />;
  if (pending.data.pending) return <PendingRecoveryKey value={pending.data.pending} action={t("recovery.done")} />;
  return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-md text-ink-secondary">{t("recovery.description")}</p>
      <Dialog
        title={t("recovery.new.title")}
        description={t("recovery.new.description")}
        open={asking}
        onOpenChange={setAsking}
        trigger={<Button>{t("recovery.new")}</Button>}
      >
        <div className="flex justify-end gap-2">
          <Button onClick={() => setAsking(false)}>{t("home.picker.cancel")}</Button>
          <Button variant="danger" loading={replace.isPending} onClick={() => replace.mutate(undefined, { onSuccess: () => setAsking(false) })}>
            {t("recovery.new.action")}
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
