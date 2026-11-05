"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useProfile, useSaveProfile } from "@/ui/client/onboarding";
import type { Profile } from "@/ui/client/contracts.generated";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";

const TONES = [
  { value: "friendly", label: t("profile.tone.friendly") },
  { value: "formal", label: t("profile.tone.formal") },
  { value: "brief", label: t("profile.tone.brief") },
];

export function ProfileForm({ action, onSaved, compact = false, onboarding = false, actions }: { action: string; onSaved?: () => void; compact?: boolean; onboarding?: boolean; actions?: ReactNode }) {
  const profile = useProfile();
  const save = useSaveProfile();
  const [draft, setDraft] = useState<Profile | null>(null);
  useEffect(() => {
    if (profile.data && !draft) setDraft(profile.data);
  }, [profile.data, draft]);
  if (profile.isError) return <ErrorState title={t("profile.error")} onRetry={() => void profile.refetch()} />;
  if (!draft) return <Skeleton className="h-6 w-full" />;
  const set = (changes: Partial<Profile>) => setDraft({ ...draft, ...changes });
  return (
    <form
      className={compact ? `grid gap-3 md:grid-cols-2 ${onboarding ? "h-full" : ""}` : "flex flex-col gap-4"}
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(draft, onSaved ? { onSuccess: onSaved } : {});
      }}
    >
      <div className={`grid gap-3 md:grid-cols-2 ${compact ? "md:col-span-2" : ""}`}>
        <Field label={t("profile.name")}>{({ invalid, ...control }) => <Input invalid={invalid} autoComplete="name" value={draft.name ?? ""} onChange={(event) => set({ name: event.target.value })} {...control} />}</Field>
        <Field label={t("profile.role")}>{({ invalid, ...control }) => <Input invalid={invalid} autoComplete="organization-title" value={draft.role ?? ""} onChange={(event) => set({ role: event.target.value })} {...control} />}</Field>
      </div>
      <Field label={t("profile.tone")} hint={t("profile.tone.hint")}>
        {({ invalid, id, "aria-describedby": describedBy }) => <Select id={id} invalid={invalid} {...(describedBy ? { describedBy } : {})} value={draft.tone ?? "friendly"} options={TONES} onChange={(tone) => set({ tone: tone as Profile["tone"] })} />}
      </Field>
      <Field label={t("profile.signature")}>{({ invalid, ...control }) => <Textarea invalid={invalid} rows={onboarding ? 1 : 2} value={draft.signature ?? ""} onChange={(event) => set({ signature: event.target.value })} {...control} />}</Field>
      {onboarding ? null : <Field label={t("profile.vips")} hint={t("profile.vips.hint")}>{({ invalid, ...control }) => <Textarea invalid={invalid} rows={2} value={draft.vips ?? ""} onChange={(event) => set({ vips: event.target.value })} {...control} />}</Field>}
      {onboarding ? null : <Field label={t("profile.about")} hint={t("profile.about.hint")}>{({ invalid, ...control }) => <Textarea invalid={invalid} rows={compact ? 2 : 3} value={draft.about ?? ""} onChange={(event) => set({ about: event.target.value })} {...control} />}</Field>}
      {save.isError ? <ErrorState title={t("profile.saveError")} /> : null}
      <div className={`flex items-center gap-3 ${compact ? "md:col-span-2" : ""} ${onboarding ? "mt-auto justify-between pt-6" : ""}`}>
        {actions}
        <Button className={onboarding ? "ml-auto" : ""} type="submit" variant="primary" loading={save.isPending}>
          {action}
        </Button>
      </div>
    </form>
  );
}
