"use client";

import { useState } from "react";
import type { SaveTrigger, Trigger } from "@/ui/client/contracts.generated";
import { useRemoveTrigger, useSaveTrigger, useTriggers } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Switch } from "@/ui/primitives/Switch";
import { SessionLink } from "@/ui/features/assistant/SessionLink";
import { t } from "@/ui/strings";

const MEMORY_DEFAULT = "default";
type Event = NonNullable<SaveTrigger["event"]>;

function TriggerForm({ initial, onSaved }: { initial?: Trigger; onSaved: () => void }) {
  const triggers = useTriggers();
  const save = useSaveTrigger();
  const builtIn = initial?.kind === "mail";
  const events = triggers.data?.events ?? [];
  const [title, setTitle] = useState(initial?.title ?? "");
  const [event, setEvent] = useState<string>(initial?.event ?? events[0]?.event ?? "mail.urgent");
  const [prompt, setPrompt] = useState(initial?.prompt ?? "");
  const [memory, setMemory] = useState<string>(initial?.context_mode ?? MEMORY_DEFAULT);
  const [keep, setKeep] = useState(initial?.keep_messages == null ? "" : String(initial.keep_messages));
  const [limit, setLimit] = useState(String(initial?.token_limit ?? 0));
  const memories = [
    { value: MEMORY_DEFAULT, label: t("schedules.context.default") },
    { value: "trim", label: t("context.mode.trim") },
    { value: "auto_compact", label: t("context.mode.auto_compact") },
  ];
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(submitted) => {
        submitted.preventDefault();
        save.mutate(
          {
            ...(initial ? { id: initial.id, enabled: initial.enabled ?? true } : {}),
            title: title.trim(),
            ...(builtIn ? {} : { event: event as Event }),
            prompt,
            token_limit: Number(limit) || 0,
            context_mode: memory === MEMORY_DEFAULT ? null : (memory as NonNullable<Trigger["context_mode"]>),
            keep_messages: keep === "" ? null : Number(keep),
          },
          {
            onSuccess: () => {
              if (!initial) {
                setTitle("");
                setPrompt("");
              }
              onSaved();
            },
          },
        );
      }}
    >
      {builtIn ? null : (
        <>
          <Field label={t("triggers.name")}>{({ invalid, ...control }) => <Input invalid={invalid} value={title} onChange={(change) => setTitle(change.target.value)} {...control} />}</Field>
          <Field label={t("triggers.event")}>{({ invalid, id }) => <Select id={id} invalid={invalid} value={event} options={events.map((row) => ({ value: row.event, label: row.label }))} onChange={setEvent} />}</Field>
          <Field label={t("triggers.prompt")} hint={t("triggers.prompt.hint")}>{({ invalid, ...control }) => <Textarea invalid={invalid} rows={2} value={prompt} onChange={(change) => setPrompt(change.target.value)} {...control} />}</Field>
        </>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        <Field label={t("schedules.context")}>{({ invalid, id }) => <Select id={id} invalid={invalid} value={memory} options={memories} onChange={setMemory} />}</Field>
        {memory !== "auto_compact" ? <Field label={t("schedules.keep")} hint={t("context.keep.hint")}>{({ invalid, ...control }) => <Input type="number" min={0} invalid={invalid} value={keep} onChange={(change) => setKeep(change.target.value)} {...control} />}</Field> : null}
      </div>
      <Field label={t("schedules.limit")} hint={t("schedules.limit.hint")}>{({ invalid, ...control }) => <Input type="number" min={0} invalid={invalid} value={limit} onChange={(change) => setLimit(change.target.value)} {...control} />}</Field>
      {save.isError ? <ErrorState title={t("triggers.saveFailed")} /> : null}
      <div>
        <Button type="submit" variant="primary" loading={save.isPending} disabled={!builtIn && (!title.trim() || !prompt.trim())}>{t(initial ? "settings.save" : "triggers.add")}</Button>
      </div>
    </form>
  );
}

function TriggerRow({ trigger, label }: { trigger: Trigger; label: string }) {
  const save = useSaveTrigger();
  const remove = useRemoveTrigger();
  const builtIn = trigger.kind === "mail";
  const toggle = (enabled: boolean) => save.mutate({ id: trigger.id, title: trigger.title, ...(builtIn ? {} : { event: trigger.event as Event }), prompt: trigger.prompt ?? "", enabled, token_limit: trigger.token_limit ?? 0, context_mode: trigger.context_mode ?? null, keep_messages: trigger.keep_messages ?? null });
  return (
    <li>
      <ExpandRow
        testid="trigger"
        label={t("schedules.edit", { title: trigger.title })}
        title={trigger.title}
        meta={label}
        aside={
          <span className="flex shrink-0 items-center gap-2">
            {trigger.session ? <SessionLink className="text-sm" session={trigger.session}>{t("triggers.chat")}</SessionLink> : null}
            <Switch label={t("rules.enabled")} hideLabel checked={trigger.enabled ?? true} onChange={toggle} />
          </span>
        }
      >
        <TriggerForm initial={trigger} onSaved={() => undefined} />
        {builtIn ? null : (
          <div className="flex justify-end">
            <IconButton icon="trash" label={t("tasks.remove", { title: trigger.title })} onClick={() => remove.mutate(trigger.id)} />
          </div>
        )}
      </ExpandRow>
    </li>
  );
}

/** What starts an agent when something happens, as schedules do when a time comes. */
export function TriggersCard() {
  const triggers = useTriggers();
  const rows = triggers.data?.triggers ?? [];
  const labelOf = (trigger: Trigger) => (trigger.kind === "mail" ? t("triggers.builtIn") : (triggers.data?.events.find((row) => row.event === trigger.event)?.label ?? trigger.event));
  return (
    <Card title={t("triggers.title")} description={t("triggers.description")}>
      <div className="flex flex-col gap-4">
        {triggers.isPending ? <Skeleton className="h-6 w-full" /> : null}
        {triggers.isError ? <ErrorState title={t("triggers.error")} onRetry={() => void triggers.refetch()} /> : null}
        <ul className="flex flex-col gap-2">
          {rows.map((trigger) => (
            <TriggerRow key={trigger.id} trigger={trigger} label={labelOf(trigger)} />
          ))}
        </ul>
        {triggers.data ? <TriggerForm key={rows.length} onSaved={() => undefined} /> : null}
      </div>
    </Card>
  );
}
