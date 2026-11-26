"use client";

import { useState } from "react";
import type { RoutineCheck } from "@/ui/client/contracts.generated";
import { useRelativeTime } from "@/ui/client/format";
import { useRemoveCheck, useRunCheck, useSaveCheck } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { ListRow } from "@/ui/primitives/List";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { Switch } from "@/ui/primitives/Switch";
import { t } from "@/ui/strings";

const DEFAULT_MINUTES = 60;
const DEFAULT_STATUS = 200;
const FEWEST_MINUTES = 5;
const MOST_MINUTES = 1440;

export const checkSaved = (check: RoutineCheck, enabled = check.enabled ?? true) => ({
  id: check.id,
  title: check.title,
  url: check.url,
  every_minutes: check.every_minutes,
  expect_status: check.expect_status ?? DEFAULT_STATUS,
  enabled,
});

/** A routine that starts on a check: a web address looked at every so often, with no AI. It tells
 * you once when it goes down and once when it's back. */
export function CheckForm({ initial, onSaved }: { initial?: RoutineCheck; onSaved: () => void }) {
  const save = useSaveCheck();
  const remove = useRemoveCheck();
  const run = useRunCheck();
  const [title, setTitle] = useState(initial?.title ?? "");
  const [url, setUrl] = useState(initial?.url ?? "");
  const [minutes, setMinutes] = useState(String(initial?.every_minutes ?? DEFAULT_MINUTES));
  const [status, setStatus] = useState(String(initial?.expect_status ?? DEFAULT_STATUS));
  const every = Number(minutes);
  const ready = Boolean(title.trim() && url.trim()) && every >= FEWEST_MINUTES && every <= MOST_MINUTES;
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(submitted) => {
        submitted.preventDefault();
        save.mutate(
          { ...(initial ? { id: initial.id, enabled: initial.enabled ?? true } : {}), title: title.trim(), url: url.trim(), every_minutes: every, expect_status: Number(status) || DEFAULT_STATUS },
          { onSuccess: onSaved },
        );
      }}
    >
      <p className="text-md text-ink-secondary">{t("checks.about")}</p>
      <Field label={t("checks.name")}>{({ invalid, ...control }) => <Input invalid={invalid} value={title} onChange={(change) => setTitle(change.target.value)} {...control} />}</Field>
      <Field label={t("checks.url")} hint={t("checks.url.hint")}>{({ invalid, ...control }) => <Input invalid={invalid} type="url" value={url} onChange={(change) => setUrl(change.target.value)} {...control} />}</Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("checks.every")} hint={t("checks.every.hint")}>{({ invalid, ...control }) => <Input invalid={invalid} type="number" min={FEWEST_MINUTES} max={MOST_MINUTES} value={minutes} onChange={(change) => setMinutes(change.target.value)} {...control} />}</Field>
        <Field label={t("checks.expect")} hint={t("checks.expect.hint")}>{({ invalid, ...control }) => <Input invalid={invalid} type="number" min={100} max={599} value={status} onChange={(change) => setStatus(change.target.value)} {...control} />}</Field>
      </div>
      {save.error ? <p className="text-sm text-status-danger">{save.error.message}</p> : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" variant="primary" loading={save.isPending} disabled={!ready}>{t(initial ? "checks.save" : "checks.create")}</Button>
        {initial ? <Button variant="quiet" loading={run.isPending} onClick={() => run.mutate(initial.id)}>{t("checks.runNow")}</Button> : null}
        {initial ? <Button variant="quiet" loading={remove.isPending} onClick={() => remove.mutate(initial.id, { onSuccess: onSaved })}>{t("schedules.remove")}</Button> : null}
      </div>
      {initial?.last_checked ? <p className="text-sm text-ink-muted">{initial.last_result}</p> : null}
    </form>
  );
}

export function CheckItem({ check, onOpen }: { check: RoutineCheck; onOpen: () => void }) {
  const save = useSaveCheck();
  const relative = useRelativeTime();
  const on = check.enabled ?? true;
  const failing = check.state === "failing";
  const state = !on ? t("schedules.paused") : failing ? t("checks.state.failing", { result: check.last_result ?? "" }) : check.last_checked ? t("checks.state.checked", { when: relative(check.last_checked) }) : t("checks.state.waiting");
  return (
    <ListRow
      testid="check"
      state={on ? "on" : "paused"}
      lead={<StatusDot tone={!on ? "idle" : failing ? "failed" : "done"} />}
      title={check.title}
      meta={`${t("checks.cadence", { minutes: check.every_minutes })} · ${state}`}
      onOpen={onOpen}
      trailing={<Switch label={t("rules.enabled")} hideLabel checked={on} onChange={(enabled) => save.mutate(checkSaved(check, enabled))} />}
    />
  );
}
