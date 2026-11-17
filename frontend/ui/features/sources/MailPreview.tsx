"use client";

import { ThreadScreen } from "@/ui/features/mail/ThreadScreen";
import { t } from "@/ui/strings";
import { PreviewFrame, type PreviewProps } from "./PreviewFrame";

/** An email thread in the quick preview, open on the cited message when there is one. */
export function MailPreview(props: PreviewProps) {
  const id = Number(props.source.ref);
  return (
    <PreviewFrame {...props} title={t("mail.reading")} testId="thread-preview">
      <div className="min-h-0 flex-1 overflow-y-auto rounded-md bg-surface-page">
        <ThreadScreen key={id} id={id} cited={props.source.message ?? null} onLeave={props.onClose} />
      </div>
    </PreviewFrame>
  );
}
