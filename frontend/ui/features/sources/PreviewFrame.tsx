"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Dialog } from "@/ui/primitives/Dialog";
import { IconButton } from "@/ui/primitives/IconButton";
import { t } from "@/ui/strings";
import { fullHref, type PreviewSource } from "./kinds";

export interface PreviewProps {
  source: PreviewSource;
  position: number;
  total: number;
  onMove: (by: number) => void;
  onClose: () => void;
}

/** The one quick preview: frosted, over the page and the chat, with the way to the full page. */
export function PreviewFrame({ title, source, position, total, onMove, onClose, actions, testId, children }: PreviewProps & { title: string; actions?: ReactNode; testId: string; children: ReactNode }) {
  return (
    <Dialog title={title} shape="glass" open onOpenChange={(open) => (open ? null : onClose())}>
      <div data-testid={testId} className="flex min-h-0 flex-1 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-1">
          {total > 1 ? (
            <>
              <IconButton icon="chevronLeft" label={t("preview.previous")} disabled={position <= 0} onClick={() => onMove(-1)} />
              <span className="text-sm tabular-nums text-ink-muted">{t("preview.position", { position: position + 1, total })}</span>
              <IconButton icon="chevronRight" label={t("preview.next")} disabled={position >= total - 1} onClick={() => onMove(1)} />
            </>
          ) : null}
          <span className="flex-1" />
          {actions}
          <Link data-testid="preview-open-full" className="focus-ring rounded-md px-2 py-1 text-md text-ink-secondary underline-offset-2 hover:underline" href={fullHref(source)} onClick={onClose}>{t("preview.openFull")}</Link>
        </div>
        {children}
      </div>
    </Dialog>
  );
}
