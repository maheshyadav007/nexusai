"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { ApiRequestError } from "@/ui/client/api";
import { useDocumentReader } from "@/ui/client/documents";
import { AskAgent } from "@/ui/features/agent/AskAgent";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";
import { DocumentViewer } from "./DocumentViewer";

/** A file on its own page, with room to read it properly. */
export function ReaderScreen() {
  const router = useRouter();
  const params = useSearchParams();
  const key = params.get("key");
  const path = params.get("path");
  const reader = useDocumentReader({ ...(key ? { key } : {}), ...(path ? { path } : {}) });
  const data = reader.data;
  return (
    <div className="mx-auto flex max-w-page flex-col gap-4 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <Button variant="quiet" className="self-start" onClick={() => router.back()}>{t("reader.back")}</Button>
          <h1 className="break-words font-serif text-display text-ink-primary">{data?.name ?? ""}</h1>
        </div>
        {data ? (
          <div className="flex shrink-0 items-center gap-2">
            {data.key ? <AskAgent context={[`document:${data.key}`]} title={data.name} /> : null}
            <a className="focus-ring rounded-sm text-md text-accent-default underline underline-offset-2" href={data.url}>{t("documents.download")}</a>
          </div>
        ) : null}
      </header>
      {reader.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {reader.isError ? <ErrorState title={t("documents.previewFailed")} description={reader.error instanceof ApiRequestError ? reader.error.detail.message : ""} /> : null}
      {data?.status_reason && data.text ? <p className="text-sm text-ink-muted">{data.status_reason}</p> : null}
      {data ? <DocumentViewer reader={data} /> : null}
    </div>
  );
}
