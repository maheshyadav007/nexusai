"use client";

import { ApiRequestError } from "@/ui/client/api";
import type { ContextProfile, ContextSettings, MailAgentSettings } from "@/ui/client/contracts.generated";
import { useContextSettings, useMailAgent, useRunMailAgent, useSaveContextSettings, useSaveMailAgent } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { Input } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { SettingRow } from "@/ui/primitives/SettingRow";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";

type Mode = NonNullable<MailAgentSettings["mode"]>;

export function MailAgentCard() {
  const toast = useToast();
  const settings = useMailAgent();
  const save = useSaveMailAgent();
  const run = useRunMailAgent();
  const options = [
    { value: "each", label: t("agentRuns.mail.each") },
    { value: "hourly", label: t("agentRuns.mail.hourly") },
    { value: "both", label: t("agentRuns.mail.both") },
  ];
  return (
    <Card title={t("agentRuns.mail.title")} description={t("agentRuns.mail.description")}>
      <SettingRow label={t("agentRuns.mail.when")} wide>
        {settings.data ? <Select label={t("agentRuns.mail.when")} value={settings.data.mode ?? "each"} options={options} onChange={(mode) => save.mutate({ mode: mode as Mode })} /> : <Skeleton className="h-6 w-full" />}
      </SettingRow>
      <div className="mt-3">
        <Button
          loading={run.isPending}
          onClick={() =>
            run.mutate(undefined, {
              onSuccess: (result) => toast({ title: t(result.outcome === "started" ? "agentRuns.mail.started" : "agentRuns.mail.nothing") }),
              onError: (error) => toast({ title: error instanceof ApiRequestError ? error.detail.message : t("agentRuns.mail.nothing") }),
            })
          }
        >
          {t("agentRuns.mail.run")}
        </Button>
      </div>
    </Card>
  );
}

function ProfileRows({ label, profile, onChange }: { label: string; profile: ContextProfile; onChange: (changes: Partial<ContextProfile>) => void }) {
  const options = [
    { value: "trim", label: t("context.mode.trim") },
    { value: "auto_compact", label: t("context.mode.auto_compact") },
  ];
  return (
    <>
      <SettingRow label={label} wide>
        <Select label={label} value={profile.mode ?? "trim"} options={options} onChange={(mode) => onChange({ mode: mode as NonNullable<ContextProfile["mode"]> })} />
      </SettingRow>
      {profile.mode !== "auto_compact" ? (
        <SettingRow label={t("context.keep")} description={t("context.keep.hint")}>
          <Input className="py-1" aria-label={`${label}: ${t("context.keep")}`} type="number" min={0} value={profile.keep_messages ?? 0} onChange={(event) => onChange({ keep_messages: Number(event.target.value) })} />
        </SettingRow>
      ) : null}
    </>
  );
}

export function ContextCard() {
  const settings = useContextSettings();
  const save = useSaveContextSettings();
  if (!settings.data) return <Card title={t("context.title")}><Skeleton className="h-6 w-full" /></Card>;
  const value: ContextSettings = settings.data;
  return (
    <Card title={t("context.title")} description={t("context.description")}>
      <div data-testid="context-settings">
        <ProfileRows label={t("context.chat")} profile={value.chat} onChange={(changes) => save.mutate({ ...value, chat: { ...value.chat, ...changes } })} />
        <ProfileRows label={t("context.triggered")} profile={value.triggered} onChange={(changes) => save.mutate({ ...value, triggered: { ...value.triggered, ...changes } })} />
      </div>
    </Card>
  );
}
