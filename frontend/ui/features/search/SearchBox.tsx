"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useDocuments } from "@/ui/client/documents";
import { useSearch } from "@/ui/client/mail";
import { usePreview } from "@/ui/features/documents/DocumentPreview";
import { Highlight } from "./SearchFilters";
import { Icon } from "@/ui/icons";
import { Dialog } from "@/ui/primitives/Dialog";
import { Input } from "@/ui/primitives/Input";
import { Kbd } from "@/ui/primitives/Kbd";
import { Pressable } from "@/ui/primitives/Pressable";
import { t } from "@/ui/strings";

const RECENT_KEY = "nexusai.recentSearches";
const MOST_RECENT = 5;
const MAIL_SHOWN = 6;
const DOCUMENTS_SHOWN = 5;
const SETTLE_MS = 180;

function recent(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function remember(text: string) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify([text, ...recent().filter((item) => item !== text)].slice(0, MOST_RECENT)));
  } catch {
    // A blocked store only means no recent searches.
  }
}

interface Result {
  id: string;
  label: string;
  detail: string;
  icon: "inbox" | "documents" | "search";
  go: () => void;
}

function Palette({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const preview = usePreview();
  const [text, setText] = useState("");
  const [settled, setSettled] = useState("");
  const [index, setIndex] = useState(0);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(text.trim()), SETTLE_MS);
    return () => clearTimeout(timer);
  }, [text]);
  const mail = useSearch({ query: settled, limit: MAIL_SHOWN }, Boolean(settled));
  const documents = useDocuments({ query: settled, limit: DOCUMENTS_SHOWN }, Boolean(settled));
  const finish = (go: () => void) => {
    if (text.trim()) remember(text.trim());
    onClose();
    go();
  };
  const openPage = () => router.push(`/search?q=${encodeURIComponent(text.trim())}`);
  const mailRows: Result[] = (mail.data?.hits ?? []).map((hit) => ({ id: `t${hit.thread.id}`, label: hit.thread.subject || t("mail.noSubject"), detail: hit.thread.sender_name ?? hit.thread.participants[0] ?? "", icon: "inbox", go: () => router.push(`/search/${hit.thread.id}?${new URLSearchParams({ q: settled, in: "mail" })}`) }));
  const documentRows: Result[] = (documents.data?.documents ?? []).map((row) => ({ id: `d${row.key}`, label: row.name, detail: row.place ?? "", icon: "documents", go: () => preview.show({ key: row.key }) }));
  const recents: Result[] = text ? [] : recent().map((item) => ({ id: `r${item}`, label: item, detail: "", icon: "search", go: () => router.push(`/search?q=${encodeURIComponent(item)}`) }));
  const all = [...recents, ...mailRows, ...documentRows];
  const chosen = Math.min(index, Math.max(all.length - 1, 0));
  const group = (title: string, rows: readonly Result[], offset: number) => (rows.length ? (
    <section aria-label={title}>
      <h3 className="px-3 py-1 text-sm text-ink-muted">{title}</h3>
      <ul>
        {rows.map((row, position) => (
          <li key={row.id} data-testid="palette-result">
            <Pressable onClick={() => finish(row.go)} className={`focus-ring flex w-full items-center gap-3 rounded-md px-3 py-2 text-left ${offset + position === chosen ? "bg-surface-sunken" : ""}`}>
              <Icon name={row.icon} className="h-4 w-4 shrink-0 text-ink-muted" />
              <span className="min-w-0 flex-1 truncate text-md text-ink-primary"><Highlight text={row.label} words={settled} /></span>
              {row.detail ? <span className="w-1/4 shrink-0 truncate text-right text-sm text-ink-muted">{row.detail}</span> : null}
            </Pressable>
          </li>
        ))}
      </ul>
    </section>
  ) : null);
  return (
    <Dialog title={t("search.title")} shape="palette" open onOpenChange={(open) => (open ? null : onClose())}>
      <div className="flex min-h-0 flex-col gap-2">
        <Input
          autoFocus
          type="search"
          aria-label={t("search.label")}
          placeholder={t("search.placeholder")}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setIndex(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setIndex(Math.min(chosen + 1, all.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setIndex(Math.max(chosen - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              const row = settled === text.trim() && index > 0 ? all[chosen] : undefined;
              if (row) finish(row.go);
              else if (text.trim()) finish(openPage);
            }
          }}
        />
        <div className="min-h-0 overflow-y-auto">
          {group(t("search.recent"), recents, 0)}
          {group(t("search.in.mail"), mailRows, recents.length)}
          {group(t("search.in.documents"), documentRows, recents.length + mailRows.length)}
          {settled && !all.length && !mail.isPending ? <p className="px-3 py-4 text-md text-ink-muted">{t("search.none")}</p> : null}
        </div>
        {text.trim() ? (
          <Pressable data-testid="palette-all" onClick={() => finish(openPage)} className="focus-ring rounded-md px-3 py-2 text-left text-md text-accent-default">{t("search.seeAll")}</Pressable>
        ) : null}
      </div>
    </Dialog>
  );
}

/** Looks like a search field, and opens instant results over the page. Also on Cmd or Ctrl K. */
export function SearchBox() {
  const [open, setOpen] = useState(false);
  const [onMac, setOnMac] = useState(false);
  useEffect(() => setOnMac(/mac/i.test(navigator.platform)), []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div role="search" className="min-w-0 flex-1">
      <Pressable data-testid="search-open" onClick={() => setOpen(true)} className="flex w-full items-center gap-2 rounded-md border border-line-subtle bg-surface-page px-3 py-2 text-left text-md text-ink-muted transition-colors duration-fast hover:bg-surface-sunken">
        <Icon name="search" className="h-4 w-4 shrink-0" />
        <span className="min-w-0 flex-1 truncate">{t("search.placeholder")}</span>
        <Kbd>{t(onMac ? "search.shortcut.mac" : "search.shortcut")}</Kbd>
      </Pressable>
      {open ? <Palette onClose={() => setOpen(false)} /> : null}
    </div>
  );
}
