"use client";

import { useRouter } from "next/navigation";
import { ContextMenu } from "@/ui/primitives/ContextMenu";
import { usePreview } from "./DocumentPreview";
import { sizeOf } from "./sizes";
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


/** Everything the agents and the person keep in Home. NexusAI's own system folder stays hidden. */
export function HomeFolderView() {
  const [path, setPath] = useState("");
  const folder = useHomeFolder(path);
  const format = useDateTime();
  const entries = folder.data?.entries ?? [];
  const preview = usePreview();
  const router = useRouter();
  const files = entries.filter((entry) => !entry.is_folder).map((entry) => ({ path: entry.path }));
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
              <ContextMenu items={[{ id: "open", label: t("menu.open"), onSelect: () => preview.show({ path: entry.path }, files) }, { id: "full", label: t("documents.openFull"), onSelect: () => router.push(`/documents/view?path=${encodeURIComponent(entry.path)}`) }]}>
              <RowButton onClick={() => preview.show({ path: entry.path }, files)}>
                <Icon name="file" className="h-4 w-4 shrink-0 text-ink-muted" />
                <span className="min-w-0 flex-1 truncate text-md text-ink-primary">{entry.label}</span>
                <span className="shrink-0 text-sm tabular-nums text-ink-muted">{sizeOf(entry.size ?? 0)}</span>
                {entry.modified ? <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(entry.modified)}</span> : null}
              </RowButton>
              </ContextMenu>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
