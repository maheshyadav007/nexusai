"use client";

import { useState } from "react";
import { useFolders } from "@/ui/client/home";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Pressable } from "@/ui/primitives/Pressable";
import { ScrollArea } from "@/ui/primitives/ScrollArea";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";

/** Browsers can't hand a web page a folder path, so the local backend lists folders instead. */
export function FolderPicker({ start, trigger, extension, onPick }: { start: string; trigger: React.ReactNode; extension?: string; onPick: (path: string) => void }) {
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState<string | null>(start);
  const folders = useFolders(path, open, extension);
  const listing = folders.data;
  return (
    <Dialog
      title={t("home.picker.title")}
      trigger={trigger}
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setPath(start);
      }}
    >
      <p data-testid="picker-path" className="mb-3 break-all font-mono text-sm text-ink-secondary">
        {listing?.path ?? path}
      </p>
      {listing?.drives?.length ? (
        <div role="group" aria-label={t("home.picker.drives")} className="mb-3 flex flex-wrap gap-1">
          {listing.drives.map((drive) => <Button key={drive} variant="quiet" className="py-px" onClick={() => setPath(drive)}>{drive}</Button>)}
        </div>
      ) : null}
      {folders.isError ? <ErrorState title={t("home.picker.error")} onRetry={() => void folders.refetch()} /> : null}
      {folders.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {listing ? (
        <ScrollArea className="h-drawer max-h-popover rounded-md border border-line-subtle">
          <ul className="flex flex-col gap-px p-1">
            {listing.parent ? (
              <li>
                <Pressable onClick={() => setPath(listing.parent ?? null)} className="focus-ring flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left text-md text-ink-secondary transition-colors duration-fast hover:bg-surface-sunken">
                  <Icon name="collapse" />
                  {t("home.picker.up")}
                </Pressable>
              </li>
            ) : null}
            {listing.folders.map((name) => (
              <li key={name}>
                <Pressable onClick={() => setPath(`${listing.path}/${name}`)} className="focus-ring flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left text-md text-ink-primary transition-colors duration-fast hover:bg-surface-sunken">
                  <Icon name="all" />
                  <span className="truncate">{name}</span>
                </Pressable>
              </li>
            ))}
            {(listing.files ?? []).map((name) => (
              <li key={name}>
                <Pressable onClick={() => {
                    onPick(`${listing.path}/${name}`);
                    setOpen(false);
                  }}
                  className="focus-ring flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left text-md text-accent-default transition-colors duration-fast hover:bg-surface-sunken"
                >
                  <Icon name="documents" />
                  <span className="truncate">{name}</span>
                </Pressable>
              </li>
            ))}
            {listing.folders.length === 0 && !listing.files?.length ? <li className="px-2 py-1 text-md text-ink-muted">{t("home.picker.empty")}</li> : null}
          </ul>
        </ScrollArea>
      ) : null}
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="quiet" onClick={() => setOpen(false)}>
          {t("home.picker.cancel")}
        </Button>
        {extension ? null : (
          <Button
            variant="primary"
            disabled={!listing}
            onClick={() => {
              if (listing) onPick(listing.path);
              setOpen(false);
            }}
          >
            {t("home.picker.use")}
          </Button>
        )}
      </div>
    </Dialog>
  );
}
