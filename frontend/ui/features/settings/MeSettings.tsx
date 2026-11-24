"use client";

import { useState } from "react";
import type { MailMe } from "@/ui/client/contracts.generated";
import { useMe, useNamedYou, useSaveMe } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { TextLink } from "@/ui/primitives/TextLink";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";
import { NotAboutMe } from "@/ui/features/mail/NotAboutMe";
import { useOpenSource } from "@/ui/features/sources/context";
import { fullHref, mailSource } from "@/ui/features/sources/kinds";

type Part = "names" | "addresses" | "ids" | "not_you";

/** One list of what names the person: each item removable, one box to add. Saved as it changes. */
function Chips({ part, me, title, hint }: { part: Part; me: MailMe; title: string; hint?: string }) {
  const save = useSaveMe();
  const toast = useToast();
  const [adding, setAdding] = useState("");
  const items = me[part] ?? [];
  const change = (next: string[]) => save.mutate({ ...me, [part]: next }, { onError: () => toast({ title: t("me.saveError"), tone: "danger" }) });
  const add = () => {
    const value = adding.trim();
    if (!value) return;
    change([...items, value]);
    setAdding("");
  };
  return (
    <section data-testid={`me-${part}`} aria-label={title} className="flex flex-col gap-2">
      <h3 className="text-sm font-medium text-ink-primary">{title}</h3>
      <div className="flex flex-wrap items-center gap-2">
        {items.map((item) => (
          <span key={item} className="inline-flex items-center gap-1 rounded-full bg-surface-sunken py-1 pl-3 pr-1 text-sm text-ink-primary">
            {item}
            <IconButton icon="close" label={t("me.remove", { item })} onClick={() => change(items.filter((other) => other !== item))} />
          </span>
        ))}
        <form className="flex items-center gap-1" onSubmit={(event) => { event.preventDefault(); add(); }}>
          <div className="w-48"><Input aria-label={t(`me.addPlaceholder.${part}`)} placeholder={t(`me.addPlaceholder.${part}`)} value={adding} onChange={(event) => setAdding(event.target.value)} /></div>
          <Button type="submit" variant="quiet" disabled={!adding.trim()}>{t("me.add")}</Button>
        </form>
      </div>
      {hint ? <p className="text-sm text-ink-muted">{hint}</p> : null}
    </section>
  );
}

/** What naming the person let through lately, each with the words that did it, and a way to say no. */
function NamedLately() {
  const named = useNamedYou();
  const openSource = useOpenSource();
  const items = named.data?.items ?? [];
  return (
    <Card title={t("me.named.title")}>
      {named.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {named.data && !items.length ? <EmptyState icon="readByAi" title={t("me.named.empty")} /> : null}
      <ul className="flex flex-col">
        {items.map((item) => (
          <li key={item.thread} data-testid="named-you" className="flex flex-col gap-1 border-t border-line-subtle py-3 first:border-t-0">
            <div className="flex justify-between gap-3 text-sm text-ink-muted">
              <span>{t("me.named.in", { sender: item.sender, folder: item.folder ?? "" })}</span>
              <span>{new Date(item.date).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</span>
            </div>
            <q className="text-md text-ink-primary">{item.quote}</q>
            <div className="flex justify-between gap-3 text-sm">
              <TextLink
                href={fullHref(mailSource(item.thread))}
                onClick={(event) => {
                  event.preventDefault();
                  openSource.open({ ...mailSource(item.thread), title: item.subject });
                }}
                className="min-w-0 truncate text-ink-muted"
              >
                {item.subject}
              </TextLink>
              <NotAboutMe thread={item.thread} quote={item.quote} />
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function MeSettings() {
  const me = useMe();
  const data = me.data;
  return (
    <div className="flex flex-col gap-4">
      <Card title={t("me.title")} description={t("me.description", { name: data?.names?.[0] ?? "" })}>
        {me.isError ? <ErrorState title={t("me.error")} onRetry={() => void me.refetch()} /> : null}
        {me.isPending ? <Skeleton className="h-6 w-full" /> : null}
        {data ? (
          <div className="flex flex-col gap-5">
            <Chips part="names" me={data} title={t("me.names")} />
            <Chips part="addresses" me={data} title={t("me.addresses")} />
            <Chips part="ids" me={data} title={t("me.ids")} hint={t("me.ids.hint", { id: data.ids?.[0] ?? "" })} />
            <div className="border-t border-line-subtle pt-4"><Chips part="not_you" me={data} title={t("me.notYou")} hint={t("me.notYou.hint")} /></div>
          </div>
        ) : null}
      </Card>
      <NamedLately />
    </div>
  );
}
