"use client";

import { t } from "@/ui/strings";
import { MailList } from "./MailList";
import { PstImportCard } from "./PstImportCard";

export function ArchiveScreen() {
  return (
    <div className="flex h-full flex-col">
      <div className="mx-auto w-full max-w-content px-6 pt-6">
        <PstImportCard />
      </div>
      <div className="min-h-0 flex-1">
        <MailList title={t("nav.archive")} folder="archive" emptyIcon="archive" emptyTitle="mail.empty.archive" showCategories={false} requireAccount={false} />
      </div>
    </div>
  );
}
