"use client";

import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { useCreateFolder, useFolders } from "@/ui/client/home";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Input } from "@/ui/primitives/Input";
import { Pressable } from "@/ui/primitives/Pressable";
import { ScrollArea } from "@/ui/primitives/ScrollArea";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";

// "/" and "C:\\" already end in a separator.
const inside = (folder: string, name: string) => (/[\\/]$/.test(folder) ? `${folder}${name}` : `${folder}/${name}`);
const HOME_FOLDER = "~";
const CURRENT_FOLDER = ".";

/** Browsers can't hand a web page a folder path, so the local backend lists folders instead. */
export function FolderPicker({ start, trigger, extension, onPick }: { start: string; trigger: React.ReactNode; extension?: string; onPick: (path: string) => void }) {
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState<string | null>(start);
  const folders = useFolders(path, open, extension);
  const listing = folders.data;
  const create = useCreateFolder();
  const [typed, setTyped] = useState("");
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const here = listing?.path ?? path;
  // What's above a folder that couldn't be listed, so there's always a way out.
  const above = listing?.parent ?? (path ? path.replace(/[\\/][^\\/]*[\\/]?$/, "") || "/" : null);
  const go = (next: string) => {
    setPath(next);
    setTyped("");
  };
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
      <div role="group" aria-label={t("home.picker.places")} className="mb-3 flex flex-wrap gap-1">
        <Button variant="quiet" className="py-px" data-testid="picker-home" onClick={() => go(HOME_FOLDER)}>{t("home.picker.home")}</Button>
        <Button variant="quiet" className="py-px" data-testid="picker-current" onClick={() => go(CURRENT_FOLDER)}>{t("home.picker.current")}</Button>
      </div>
      <form
        className="mb-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (typed.trim()) go(typed.trim());
        }}
      >
        <Input aria-label={t("home.picker.goTo")} data-testid="picker-go" placeholder={t("home.picker.goTo")} spellCheck={false} value={typed} onChange={(event) => setTyped(event.target.value)} />
      </form>
      {listing?.drives?.length ? (
        <div role="group" aria-label={t("home.picker.drives")} className="mb-3 flex flex-wrap gap-1">
          {listing.drives.map((drive) => <Button key={drive} variant="quiet" className="py-px" onClick={() => setPath(drive)}>{drive}</Button>)}
        </div>
      ) : null}
      {folders.isError ? <ErrorState title={t("home.picker.error")} onRetry={() => void folders.refetch()} /> : null}
      {folders.isError && above ? <div className="mb-3"><Button variant="quiet" onClick={() => go(above)}>{t("home.picker.up")}</Button></div> : null}
      {listing?.problem ? <p role="alert" data-testid="picker-problem" className="mb-3 text-sm text-status-warning">{listing.problem}</p> : null}
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
                <Pressable onClick={() => setPath(inside(listing.path, name))} className="focus-ring flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left text-md text-ink-primary transition-colors duration-fast hover:bg-surface-sunken">
                  <Icon name="all" />
                  <span className="truncate">{name}</span>
                </Pressable>
              </li>
            ))}
            {(listing.files ?? []).map((name) => (
              <li key={name}>
                <Pressable onClick={() => {
                    onPick(inside(listing.path, name));
                    setOpen(false);
                  }}
                  className="focus-ring flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left text-md text-accent-default transition-colors duration-fast hover:bg-surface-sunken"
                >
                  <Icon name="documents" />
                  <span className="truncate">{name}</span>
                </Pressable>
              </li>
            ))}
            {listing.folders.length === 0 && !listing.files?.length && !listing.problem ? <li className="px-2 py-1 text-md text-ink-muted">{t("home.picker.empty")}</li> : null}
          </ul>
        </ScrollArea>
      ) : null}
      {!extension && naming && here ? (
        <form
          className="mt-3 flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate(
              { path: here, name },
              {
                onSuccess: (made) => {
                  go(made.path);
                  setName("");
                  setNaming(false);
                },
              },
            );
          }}
        >
          <Input autoFocus aria-label={t("home.picker.newName")} data-testid="picker-new-name" placeholder={t("home.picker.newName")} spellCheck={false} value={name} onChange={(event) => setName(event.target.value)} />
          <Button type="submit" className="shrink-0" loading={create.isPending} disabled={!name.trim()}>{t("home.picker.create")}</Button>
        </form>
      ) : null}
      {create.isError && naming ? <p role="alert" className="mt-2 text-sm text-status-danger">{create.error instanceof ApiRequestError ? create.error.detail.message : t("home.picker.error")}</p> : null}
      <div className="mt-4 flex items-center gap-2">
        {!extension ? <Button variant="quiet" data-testid="picker-new" onClick={() => setNaming(!naming)}>{t("home.picker.new")}</Button> : null}
        <span className="flex-1" />
        <Button variant="quiet" onClick={() => setOpen(false)}>
          {t("home.picker.cancel")}
        </Button>
        {extension ? null : (
          <Button
            variant="primary"
            disabled={!here}
            onClick={() => {
              if (here) onPick(here);
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
