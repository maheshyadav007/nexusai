"use client";

import { useState } from "react";
import type { SaveTrigger, Trigger } from "@/ui/client/contracts.generated";
import { useRemoveTrigger, useSaveTrigger, useTriggers } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { SessionLink } from "@/ui/features/assistant/SessionLink";
import { MoreOptions, runOptions, savedRunOptions } from "./RunOptions";
import { t } from "@/ui/strings";

type Event = NonNullable<SaveTrigger["event"]>;

export const triggerSaved = (trigger: Trigger, enabled = trigger.enabled ?? true): SaveTrigger => ({
  id: trigger.id,
  title: trigger.title,
  ...(trigger.kind === "mail" ? {} : { event: trigger.event as Event }),
  prompt: trigger.prompt ?? "",
  enabled,
  token_limit: trigger.token_limit ?? 0,
  context_mode: trigger.context_mode ?? null,
  keep_messages: trigger.keep_messages ?? null,
});

/** What starts an agent when something happens, as a schedule does when a time comes. */
export function TriggerForm({ initial, onSaved }: { initial?: Trigger; onSaved: () => void }) {
  const triggers = useTriggers();
  const save = useSaveTrigger();
  const remove = useRemoveTrigger();
  const builtIn = initial?.kind === "mail";
  const events = triggers.data?.events ?? [];
  const [title, setTitle] = useState(initial?.title ?? "");
  const [event, setEvent] = useState<string>(initial?.event ?? events[0]?.event ?? "mail.urgent");
  const [prompt, setPrompt] = useState(initial?.prompt ?? "");
  const [options, setOptions] = useState(runOptions(initial));
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(submitted) => {
        submitted.preventDefault();
        save.mutate(
          {
            ...(initial ? { id: initial.id, enabled: initial.enabled ?? true } : {}),
            title: title.trim(),
            ...(builtIn ? {} : { event: event as Event }),
            prompt,
            ...savedRunOptions(options),
          },
          { onSuccess: onSaved },
        );
      }}
    >
      {initial?.session ? <div><SessionLink className="text-sm" session={initial.session}>{t("triggers.chat")}</SessionLink></div> : null}
      {builtIn ? null : (
        <>
          <Field label={t("triggers.name")}>{({ invalid, ...control }) => <Input invalid={invalid} value={title} onChange={(change) => setTitle(change.target.value)} {...control} />}</Field>
          <Field label={t("triggers.event")}>{({ invalid, id }) => <Select id={id} invalid={invalid} value={event} options={events.map((row) => ({ value: row.event, label: row.label }))} onChange={setEvent} />}</Field>
          <Field label={t("triggers.prompt")} hint={t("triggers.prompt.hint")}>{({ invalid, ...control }) => <Textarea invalid={invalid} rows={3} value={prompt} onChange={(change) => setPrompt(change.target.value)} {...control} />}</Field>
        </>
      )}
      <MoreOptions values={options} onChange={setOptions} />
      {save.isError ? <ErrorState title={t("triggers.saveFailed")} /> : null}
      <div className="flex items-center justify-between gap-3">
        <Button type="submit" variant="primary" loading={save.isPending} disabled={!builtIn && (!title.trim() || !prompt.trim())}>{t(initial ? "settings.save" : "triggers.add")}</Button>
        {initial && !builtIn ? <Button variant="quiet" loading={remove.isPending} onClick={() => remove.mutate(initial.id, { onSuccess: onSaved })}>{t("schedules.remove")}</Button> : null}
      </div>
    </form>
  );
}
