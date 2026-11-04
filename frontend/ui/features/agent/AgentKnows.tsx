"use client";

import { useExpireNote, useRetryLearning } from "@/ui/client/work";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";

import { useState } from "react";
import type { KnowledgeLayer, LearnedNote } from "@/ui/client/contracts.generated";
import { useShortDate } from "@/ui/client/format";
import { useThreads } from "@/ui/client/mail";
import { useConfirmNote, useKnowledge, useMailAgent, useMailPreview, useReadMore, useRemoveNote, useSaveMailAgent } from "@/ui/client/work";
import { Icon } from "@/ui/icons";
import { Badge } from "@/ui/primitives/Badge";
import { SessionGeneration } from "@/ui/features/agent/SessionGeneration";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { CodeView } from "@/ui/primitives/CodeView";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Select } from "@/ui/primitives/Select";
import { SettingRow } from "@/ui/primitives/SettingRow";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Switch } from "@/ui/primitives/Switch";
import { TextLink } from "@/ui/primitives/TextLink";
import { TextView } from "@/ui/primitives/TextView";
import { t, tn, type StringKey } from "@/ui/strings";

// How much more it reads at a time when asked, so the cost of one click stays small.
const READ_MORE_BATCH = 30;
const NOT_READ = "";
const TRUST_LABEL: Record<string, StringKey> = { "built-in": "knows.trust.builtIn", yours: "knows.trust.yours", counted: "knows.trust.counted", mixed: "knows.trust.mixed" };
const LAYER_LABEL: Record<string, StringKey> = {
  "System prompt": "knows.layer.system",
  "Agent prompt": "knows.layer.agent",
  "About the person": "knows.layer.about",
  "Personalized prompts": "knows.layer.personal",
  "What you corrected": "knows.layer.corrections",
  "How they want the brief": "knows.layer.brief",
  "What the mailbox shows": "knows.layer.mailbox",
  Memory: "knows.layer.memory",
};

function layerTitle(name: string): string {
  const key = LAYER_LABEL[name];
  return key ? t(key) : name;
}

function Layers({ layers }: { layers: readonly KnowledgeLayer[] }) {
  return (
    <ol aria-label={t("knows.layers")} className="flex flex-col gap-2">
      {layers.map((layer, index) => {
        const trust = TRUST_LABEL[layer.trust];
        return (
          <li key={layer.name}>
            <ExpandRow label={t("prompts.open", { title: layerTitle(layer.name) })} testid="knowledge-layer" title={`${index + 1}. ${layerTitle(layer.name)}`} meta={t("knows.layer.size", { count: layer.text.length })} aside={trust ? <Badge>{t(trust)}</Badge> : null}>
              <TextView title={layerTitle(layer.name)} text={layer.text} />
            </ExpandRow>
          </li>
        );
      })}
    </ol>
  );
}

function Note({ note }: { note: LearnedNote }) {
  const confirm = useConfirmNote();
  const remove = useRemoveNote();
  const expire = useExpireNote();
  const [expiry,setExpiry] = useState(note.expires_at?.slice(0,10) ?? "");
  return (
    <li data-testid="learned-note" className="group flex items-start justify-between gap-3 border-b border-line-subtle py-2">
      <div className="min-w-0 flex-1"><p className="break-words text-md text-ink-primary">{note.text}</p>
        {note.account ? <p className="text-sm text-ink-muted">{note.account}</p> : null}
        {note.seen_at ? <details className="mt-2 text-sm text-ink-secondary"><summary className="focus-ring cursor-pointer">{t("knows.note.expiry")}</summary><Field label={t("knows.note.expiry")}>{({invalid,...control}) => <Input {...control} invalid={invalid} type="date" value={expiry} onChange={event => setExpiry(event.target.value)} />}</Field><Button loading={expire.isPending} onClick={() => expire.mutate({line:note.line,revision:note.revision ?? 1,expires_at:expiry ? `${expiry}T23:59:59Z` : null})}>{t("knows.note.setExpiry")}</Button></details> : null}
        {expire.isError || confirm.isError || remove.isError ? <ErrorState title={t("knows.error")} /> : null}
      </div>
      <span className="flex shrink-0 items-center gap-1">
        {note.thread ? <TextLink className="text-sm" href={`/mail/all/${note.thread}`}>{t("knows.note.source")}</TextLink> : null}
        {note.expires_at && new Date(note.expires_at).getTime() <= Date.now() ? <Badge>{t("knows.note.expired")}</Badge> : note.confirmed ? <Badge>{t("knows.note.confirmed")}</Badge> : <Button variant="quiet" loading={confirm.isPending} onClick={() => confirm.mutate(note.line)}>{t("knows.note.confirm")}</Button>}
        <Button variant="quiet" loading={remove.isPending} onClick={() => remove.mutate(note.line)}>{t("knows.note.remove")}</Button>
      </span>
    </li>
  );
}

function Notes({ notes }: { notes: readonly LearnedNote[] }) {
  if (!notes.length) return <EmptyState icon="memory" title={t("knows.notes.empty")} />;
  const sections = [...new Set(notes.map((note) => note.section))];
  return (
    <div className="flex flex-col gap-4">
      {sections.map((section) => (
        <section key={section || "notes"} aria-label={section || t("knows.notes")}>
          {section ? <h3 className="text-sm font-medium text-ink-muted">{section}</h3> : null}
          <ul className="flex flex-col">
            {notes.filter((note) => note.section === section).map((note) => <Note key={note.line} note={note} />)}
          </ul>
        </section>
      ))}
    </div>
  );
}

function OnItsOwn() {
  const settings = useMailAgent();
  const save = useSaveMailAgent();
  if (!settings.data) return null;
  const change = (part: { morning_brief?: boolean; inbox_review?: boolean }) => save.mutate({ mode: settings.data.mode, ...part });
  return (
    <Card title={t("knows.own.title")} description={t("knows.own.description")}>
      <SettingRow label={t("knows.own.brief")} description={t("knows.own.brief.description")}>
        <Switch hideLabel label={t("knows.own.brief")} checked={settings.data.morning_brief ?? false} onChange={(checked) => change({ morning_brief: checked })} />
      </SettingRow>
      <SettingRow label={t("knows.own.review")} description={t("knows.own.review.description")}>
        <Switch hideLabel label={t("knows.own.review")} checked={settings.data.inbox_review ?? false} onChange={(checked) => change({ inbox_review: checked })} />
      </SettingRow>
    </Card>
  );
}

/** Everything the Mail agent has to go on, so nothing about the person is kept out of sight. */
export function AgentKnows() {
  const knowledge = useKnowledge();
  const readMore = useReadMore();
  const retryLearning = useRetryLearning();
  const format = useShortDate();
  if (knowledge.isPending) return <Skeleton className="h-6 w-full" />;
  if (knowledge.isError) return <ErrorState title={t("knows.error")} onRetry={() => void knowledge.refetch()} />;
  const data = knowledge.data;
  const reading = data.learning_state === "reading" || data.learning_state === "wrapping";
  return (
    <div className="flex flex-col gap-4">
      <Card title={t("knows.notes")} description={t("knows.notes.description")}>
        <div className="flex flex-col gap-3">
          <p data-testid="knows-reading" className="text-sm tabular-nums text-ink-muted">
            {reading ? t("knows.reading", { done: data.learning_done, total: data.learning_total }) : t("knows.read", { judged: data.judged, left: data.conversations_unread })}
          </p>
          <SessionGeneration session="mail-agent" />
          {data.learning_state === "failed" ? <ErrorState title={t("knows.learning.failed")} onRetry={() => retryLearning.mutate()} /> : null}
          <Notes notes={data.notes} />
          {data.conversations_unread && !reading ? (
            <div><Button loading={readMore.isPending} onClick={() => readMore.mutate(READ_MORE_BATCH)}>{t("knows.readMore", { count: READ_MORE_BATCH })}</Button></div>
          ) : null}
        </div>
      </Card>
      <Card title={t("knows.corrections")} description={t("knows.corrections.description")}>
        {data.corrections.length ? (
          <ul className="flex flex-col">
            {data.corrections.map((item) => (
              <li key={`${item.sender}-${item.field}-${item.value}`} data-testid="knows-correction" className="flex items-baseline justify-between gap-3 border-b border-line-subtle py-2 text-md">
                <span className="min-w-0 truncate text-ink-primary">{t("knows.correction", { sender: item.sender, said: item.said })}</span>
                <span className="shrink-0 text-sm tabular-nums text-ink-muted">{tn("knows.times", item.times)}</span>
              </li>
            ))}
          </ul>
        ) : <p className="text-md text-ink-muted">{t("knows.corrections.empty")}</p>}
      </Card>
      <Card title={t("knows.contacts")} description={t("knows.contacts.description")}>
        {data.contacts.length ? (
          <ul className="flex flex-col">
            {data.contacts.map((item) => (
              <li key={item.address} data-testid="knows-contact" className="flex items-baseline justify-between gap-3 border-b border-line-subtle py-2 text-md">
                <span className="min-w-0 truncate text-ink-primary">{item.address}</span>
                <span className="shrink-0 text-sm tabular-nums text-ink-muted">{t("knows.contact", { count: item.written, when: format(item.last) })}</span>
              </li>
            ))}
          </ul>
        ) : <p className="text-md text-ink-muted">{t("knows.contacts.empty")}</p>}
      </Card>
      <OnItsOwn />
      <Card title={t("knows.brief")} description={t("knows.brief.description")}>
        {data.brief_reactions?.length ? (
          <ul className="flex flex-col">
            {data.brief_reactions.map((item) => (
              <li key={item.day} data-testid="knows-brief-reaction" className="flex items-baseline gap-3 border-b border-line-subtle py-2 text-md">
                <span className="shrink-0 text-sm tabular-nums text-ink-muted">{format(item.day)}</span>
                {item.rating ? <Icon name={item.rating === "up" ? "like" : "dislike"} className="h-3 w-3 shrink-0 self-center text-ink-secondary" /> : null}
                <span className="min-w-0 break-words text-ink-primary">{item.comment}</span>
              </li>
            ))}
          </ul>
        ) : <p className="text-md text-ink-muted">{t("knows.brief.empty")}</p>}
      </Card>
      <Card title={t("knows.layers")} description={t("knows.layers.description")}>
        <Layers layers={data.layers} />
      </Card>
    </div>
  );
}

/** Pick a conversation and see the very text the model would be sent for it. Calls no model. */
export function AgentSees() {
  const threads = useThreads("inbox", null);
  const [chosen, setChosen] = useState(NOT_READ);
  const preview = useMailPreview(chosen ? Number(chosen) : null);
  const rows = (threads.data?.pages ?? []).flatMap((page) => page.threads).slice(0, 40);
  return (
    <div className="flex flex-col gap-4">
      <p className="text-md text-ink-secondary">{t("knows.sees.description")}</p>
      <Select label={t("knows.sees.choose")} placeholder={t("knows.sees.placeholder")} value={chosen} options={rows.map((row) => ({ value: String(row.id), label: row.subject || t("mail.noSubject") }))} onChange={setChosen} />
      {preview.isFetching ? <Skeleton className="h-6 w-full" /> : null}
      {preview.isError ? <ErrorState title={t("knows.error")} onRetry={() => void preview.refetch()} /> : null}
      {preview.data ? (
        <div className="flex flex-col gap-3">
          <p data-testid="knows-tokens" className="text-sm tabular-nums text-ink-muted">{t("knows.sees.tokens", { count: preview.data.approx_tokens })}</p>
          <Layers layers={preview.data.layers} />
          <Card title={t("knows.sees.task")}>
            <CodeView label={t("knows.sees.task")} text={`${preview.data.given}\n\n${preview.data.instruction}`} />
          </Card>
        </div>
      ) : null}
    </div>
  );
}
