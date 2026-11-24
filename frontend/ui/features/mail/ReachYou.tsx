"use client";

import { useEffect, useState } from "react";
import type { MailMe, MeExample } from "@/ui/client/contracts.generated";
import { useMe, useMePreview, useSaveMe } from "@/ui/client/mail";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Popover } from "@/ui/primitives/Popover";
import { BareInput, Pressable } from "@/ui/primitives/Pressable";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t, tn } from "@/ui/strings";

const fold = (text: string) => text.trim().toLocaleLowerCase();
// As many as the person's saved names hold.
const MOST = 20;

/** After sorting: the names that mean the person, theirs and their teams' in one list, filled
 *  from their mail, each with how many hidden replies it lets through, and a few of those beside
 *  it. Saving lets those replies reach the AI. */
export function ReachYouScreen({ onDone, onBack }: { onDone: () => void; onBack?: () => void }) {
  const me = useMe();
  const save = useSaveMe();
  const [items, setItems] = useState<string[] | null>(null);
  const [adding, setAdding] = useState("");
  // Full name, first name, and the part of each address before the @, until the person changes it.
  useEffect(() => {
    if (me.data && items === null) setItems([...new Map([...(me.data.names ?? []), ...(me.data.ids ?? [])].map((item) => [fold(item), item])).values()].slice(0, MOST));
  }, [me.data, items]);
  const preview = useMePreview(items ?? []);
  if (me.isError) return <ErrorState title={t("me.error")} onRetry={() => void me.refetch()} />;
  if (!me.data || items === null) return <div className="p-6"><Skeleton className="h-6 w-full" /></div>;
  const ids = new Set((me.data.ids ?? []).map(fold));
  const add = () => {
    const value = adding.trim().replace(/\s+/g, " ");
    if (value && items.length < MOST && !items.some((item) => fold(item) === fold(value))) setItems([...items, value]);
    setAdding("");
  };
  const finish = () => save.mutate(
    { ...me.data, names: items.filter((item) => !ids.has(fold(item))) as MailMe["names"], ids: items.filter((item) => ids.has(fold(item))) as MailMe["ids"] },
    { onSuccess: onDone },
  );
  const counts = preview.data?.counts ?? {};
  const examples = preview.data?.examples ?? [];
  return <div className="flex min-h-full flex-1 flex-col">
    <div className="flex flex-1 flex-wrap items-start justify-center gap-7 px-5 py-7">
      <div className="flex w-full max-w-reading min-w-0 flex-col gap-5">
        <header className="flex flex-col gap-2">
          <h1 className="font-serif text-title text-ink-primary">{t("reach.title")}</h1>
          <p className="text-md leading-relaxed text-ink-secondary">{t("reach.lead")}</p>
        </header>
        <ul aria-label={t("reach.list")} className="flex flex-col divide-y divide-line-subtle rounded-lg border border-line-subtle bg-surface-raised">
          {items.map((item) => <li key={item} data-testid="reach-name" className="flex items-center gap-3 px-4 py-3">
            <span className="min-w-0 flex-1 break-words text-md text-ink-primary">{item}</span>
            <span className="shrink-0 text-sm tabular-nums text-ink-muted">{preview.data ? tn("reach.count", counts[item] ?? 0) : ""}</span>
            <IconButton icon="close" label={t("me.remove", { item })} onClick={() => setItems(items.filter((other) => other !== item))} />
          </li>)}
          <li className="flex items-center gap-3 px-4 py-3">
            <Icon name="add" className="h-4 w-4 shrink-0 text-ink-faint" />
            <BareInput aria-label={t("reach.add")} placeholder={t("reach.add")} value={adding} maxLength={80} onChange={(event) => setAdding(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); add(); } }} onBlur={add} className="min-w-0 flex-1 text-md outline-none" />
          </li>
        </ul>
        <p className="flex flex-wrap items-center gap-1 text-sm text-ink-muted">
          {t("reach.note")}
          <Popover label={t("reach.how")} align="start" trigger={<Pressable className="rounded-sm text-accent-default underline underline-offset-2">{t("reach.how")}</Pressable>}>
            <ul className="flex max-w-reading list-disc flex-col gap-2 pl-4 text-sm text-ink-secondary">
              <li>{t("reach.how.hidden")}</li>
              <li>{t("reach.how.person")}</li>
              <li>{t("reach.how.told")}</li>
            </ul>
          </Popover>
        </p>
      </div>
      <aside aria-label={t("reach.examples")} className="flex w-full max-w-reading min-w-0 flex-col gap-3 lg:max-w-popover lg:pt-2">
        <p className="text-sm font-medium text-ink-muted">{t("reach.examples")}</p>
        {!preview.data ? <Skeleton className="h-6 w-full" /> : examples.length ? <>
          {examples.map((example, index) => <Example key={index} example={example} />)}
          <p className="text-sm text-ink-faint">{t("reach.examples.note")}</p>
        </> : <p className="text-sm text-ink-muted">{t("reach.examples.none")}</p>}
      </aside>
    </div>
    <footer className="sticky bottom-0 flex flex-wrap items-center justify-between gap-3 border-t border-line-subtle bg-surface-raised px-5 py-3 md:px-6">
      <p className="text-sm text-ink-muted">{save.isError ? <span role="alert" className="text-status-danger">{t("me.saveError")}</span> : t("reach.later")}</p>
      <div className="flex items-center gap-2">
        {onBack ? <Button variant="quiet" onClick={onBack}>{t("setup.back")}</Button> : null}
        <Button variant="primary" loading={save.isPending} onClick={finish}>{t("reach.done")}</Button>
      </div>
    </footer>
  </div>;
}

/** One reply that would reach the AI: who wrote it and where, then its line with the name in bold. */
function Example({ example }: { example: MeExample }) {
  const at = example.word ? example.quote.toLocaleLowerCase().indexOf(example.word.toLocaleLowerCase()) : -1;
  return <div data-testid="reach-example" className="flex flex-col gap-1 rounded-md border border-line-subtle bg-surface-raised px-3 py-2">
    <span className="text-sm text-ink-muted">{example.folder ? t("reach.example.from", { sender: example.sender, folder: example.folder }) : example.sender}</span>
    <span className="break-words text-md text-ink-secondary">
      {at < 0 ? example.quote : <>{example.quote.slice(0, at)}<b className="font-medium text-accent-default">{example.quote.slice(at, at + example.word.length)}</b>{example.quote.slice(at + example.word.length)}</>}
    </span>
  </div>;
}
