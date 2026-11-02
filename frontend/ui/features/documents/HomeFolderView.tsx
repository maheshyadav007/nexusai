"use client";

import Link from "next/link";
import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { useDateTime } from "@/ui/client/format";
import { useHomeFolder } from "@/ui/client/documents";
import { Icon } from "@/ui/icons";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Pressable, RowButton } from "@/ui/primitives/Pressable";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";

const sizeOf = (bytes: number) => new Intl.NumberFormat(undefined, { style: "unit", unit: bytes < 1024 ** 2 ? "kilobyte" : "megabyte", maximumFractionDigits: 1 }).format(bytes < 1024 ** 2 ? bytes / 1024 : bytes / 1024 ** 2);

/** Everything the agents and the person keep in Home. NexusAI's own system folder stays hidden. */
export function HomeFolderView() {
  const [path, setPath] = useState("");
  const folder = useHomeFolder(path);
  const format = useDateTime();
  const entries = folder.data?.entries ?? [];
  const steps = path ? path.split("/") : [];
  return (
    <section aria-label={t("documents.view.home")} className="flex flex-col gap-3">
      <nav aria-label={t("documents.home.where")} className="flex flex-wrap items-center gap-1 text-md">
        <Pressable onClick={() => setPath("")} className="rounded-sm text-ink-muted transition-colors duration-fast hover:text-ink-primary">{t("documents.home.top")}</Pressable>
        {steps.map((step, index) => (
          <span key={`${index}-${step}`} className="flex items-center gap-1">
            <Icon name="chevronRight" className="h-3 w-3 text-ink-faint" />
            <Pressable onClick={() => setPath(steps.slice(0, index + 1).join("/"))} className="rounded-sm text-ink-secondary transition-colors duration-fast hover:text-ink-primary">{step}</Pressable>
          </span>
        ))}
      </nav>
      {folder.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {folder.isError ? <ErrorState title={t("documents.home.failed")} description={folder.error instanceof ApiRequestError ? folder.error.detail.message : ""} onRetry={() => void folder.refetch()} /> : null}
      {folder.isSuccess && !entries.length ? <EmptyState icon="folder" title={t("documents.home.empty")} /> : null}
      <ul className="flex flex-col gap-px">
        {entries.map((entry) => (
          <li key={entry.path} data-testid="home-entry">
            {entry.is_folder ? (
              <RowButton onClick={() => setPath(entry.path)}>
                <Icon name="folder" className="h-4 w-4 shrink-0 text-ink-muted" />
                <span className="min-w-0 flex-1 truncate text-md text-ink-primary">{entry.label}</span>
              </RowButton>
            ) : (
              <Link href={`/documents/view?path=${encodeURIComponent(entry.path)}`} className="focus-ring flex w-full items-center gap-3 rounded-md px-3 py-2 transition-colors duration-fast hover:bg-surface-sunken">
                <Icon name="file" className="h-4 w-4 shrink-0 text-ink-muted" />
                <span className="min-w-0 flex-1 truncate text-md text-ink-primary">{entry.label}</span>
                <span className="shrink-0 text-sm tabular-nums text-ink-muted">{sizeOf(entry.size ?? 0)}</span>
                {entry.modified ? <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(entry.modified)}</span> : null}
              </Link>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
