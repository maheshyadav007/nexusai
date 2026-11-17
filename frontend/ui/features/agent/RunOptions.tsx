"use client";

import { useState, type ReactNode } from "react";
import type { ContextMode } from "@/ui/client/contracts.generated";
import { Button } from "@/ui/primitives/Button";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { t } from "@/ui/strings";

export const MEMORY_DEFAULT = "default";

/** What a run remembers and may spend. Schedules and triggers share it, folded away until wanted. */
export interface RunOptionValues {
  memory: string;
  keep: string;
  limit: string;
}

export const runOptions = (initial?: { context_mode?: ContextMode | null; keep_messages?: number | null; token_limit?: number | null }): RunOptionValues => ({
  memory: initial?.context_mode ?? MEMORY_DEFAULT,
  keep: initial?.keep_messages == null ? "" : String(initial.keep_messages),
  limit: String(initial?.token_limit ?? 0),
});

export const savedRunOptions = (values: RunOptionValues) => ({
  token_limit: Number(values.limit) || 0,
  context_mode: values.memory === MEMORY_DEFAULT ? null : (values.memory as ContextMode),
  keep_messages: values.keep === "" ? null : Number(values.keep),
});

export function MoreOptions({ values, onChange, children }: { values: RunOptionValues; onChange: (values: RunOptionValues) => void; children?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const memories = [
    { value: MEMORY_DEFAULT, label: t("schedules.context.default") },
    { value: "trim", label: t("context.mode.trim") },
    { value: "auto_compact", label: t("context.mode.auto_compact") },
  ];
  return (
    <div className="flex flex-col gap-3">
      <div>
        <Button variant="quiet" className="-mx-3" aria-expanded={open} onClick={() => setOpen(!open)}>{t(open ? "schedules.fewer" : "schedules.more")}</Button>
      </div>
      {open ? (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label={t("schedules.context")}>{({ invalid, id }) => <Select id={id} invalid={invalid} value={values.memory} options={memories} onChange={(memory) => onChange({ ...values, memory })} />}</Field>
            {values.memory !== "auto_compact" ? <Field label={t("schedules.keep")} hint={t("context.keep.hint")}>{({ invalid, ...control }) => <Input type="number" min={0} invalid={invalid} value={values.keep} onChange={(event) => onChange({ ...values, keep: event.target.value })} {...control} />}</Field> : null}
          </div>
          <Field label={t("schedules.limit")} hint={t("schedules.limit.hint")}>{({ invalid, ...control }) => <Input type="number" min={0} invalid={invalid} value={values.limit} onChange={(event) => onChange({ ...values, limit: event.target.value })} {...control} />}</Field>
          {children}
        </>
      ) : null}
    </div>
  );
}
