"use client";

import { useEffect, useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { GuardRule, Permissions, QuietHours, SendCheckSettings } from "@/ui/client/contracts.generated";
import { usePermissions, useSavePermissions } from "@/ui/client/sessions";
import { useGuardRules, useQuietHours, useSaveGuardRules, useSaveQuietHours, useSaveSendChecks, useSendChecks, useSetCap, useTestGuard, useUsage } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Segmented } from "@/ui/primitives/Segmented";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Switch } from "@/ui/primitives/Switch";
import { useToast } from "@/ui/primitives/Toast";
import { t, tn } from "@/ui/strings";

const LEVELS = [
  { value: "off", label: t("permissions.off") },
  { value: "ask", label: t("permissions.ask") },
  { value: "allow", label: t("permissions.allow") },
] as const;
const CHECK_LEVELS = [
  { value: "off", label: t("permissions.off") },
  { value: "warn", label: t("checks.warn") },
  { value: "block", label: t("checks.block") },
] as const;
const ACTIONS = [
  { value: "mask", label: t("guard.mask") },
  { value: "block", label: t("checks.block") },
] as const;

export function PermissionsSettings() {
  const permissions = usePermissions();
  const save = useSavePermissions();
  const [folder, setFolder] = useState("");
  if (permissions.isPending) return <Card title={t("permissions.title")}><Skeleton className="h-6 w-full" /></Card>;
  if (permissions.isError) return <Card title={t("permissions.title")}><ErrorState title={t("permissions.error")} onRetry={() => void permissions.refetch()} /></Card>;
  const value = permissions.data;
  const update = (changes: Partial<Permissions>) => save.mutate({ ...value, ...changes });
  const folders = value.folders ?? [];
  return (
    <Card title={t("permissions.title")} description={t("permissions.description")}>
      <div className="flex flex-col gap-4">
        <Segmented label={t("permissions.read")} value={value.read ?? "allow"} options={LEVELS} onChange={(read) => update({ read })} />
        <Segmented label={t("permissions.write")} value={value.write ?? "allow"} options={LEVELS} onChange={(write) => update({ write })} />
        <Segmented label={t("permissions.command")} value={value.command ?? "ask"} options={LEVELS} onChange={(command) => update({ command })} />
        <Switch label={t("permissions.full")} checked={value.full_computer_access ?? false} onChange={(full_computer_access) => update({ full_computer_access })} />
        <p className="text-sm text-ink-muted">{t("permissions.commandsNote")}</p>
        <p className="text-sm text-ink-muted">{t("permissions.untrustedNote")}</p>
        <form
          className="flex items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            update({ folders: [...folders, folder.trim()] });
            setFolder("");
          }}
        >
          <div className="min-w-0 flex-1"><Field label={t("permissions.addFolder")}>{({ invalid, ...control }) => <Input invalid={invalid} spellCheck={false} value={folder} onChange={(event) => setFolder(event.target.value)} {...control} />}</Field></div>
          <Button type="submit" disabled={!folder.trim()}>{t("memory.addAction")}</Button>
        </form>
        <ul className="flex flex-col gap-1">
          {folders.map((item) => (
            <li key={item} className="flex items-center justify-between gap-2 text-md text-ink-secondary">
              <span className="min-w-0 break-all">{item}</span>
              <IconButton icon="close" label={t("tasks.remove", { title: item })} onClick={() => update({ folders: folders.filter((entry) => entry !== item) })} />
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

export function SendCheckSettingsCard() {
  const checks = useSendChecks();
  const save = useSaveSendChecks();
  if (!checks.data) return <Card title={t("checks.title")}><Skeleton className="h-6 w-full" /></Card>;
  const value = checks.data;
  const update = (changes: Partial<SendCheckSettings>) => save.mutate({ ...value, ...changes });
  return (
    <Card title={t("checks.title")} description={t("checks.description")}>
      <div className="flex flex-col gap-4">
        <Segmented label={t("checks.external")} value={value.external_recipient ?? "warn"} options={CHECK_LEVELS} onChange={(external_recipient) => update({ external_recipient })} />
        <Segmented label={t("checks.attachment")} value={value.missing_attachment ?? "warn"} options={CHECK_LEVELS} onChange={(missing_attachment) => update({ missing_attachment })} />
        <Segmented label={t("checks.newer")} value={value.newer_reply ?? "warn"} options={CHECK_LEVELS} onChange={(newer_reply) => update({ newer_reply })} />
        <Field label={t("checks.undo")}>{({ invalid, ...control }) => <Input type="number" min={0} max={60} invalid={invalid} value={value.undo_seconds ?? 5} onChange={(event) => update({ undo_seconds: Number(event.target.value) })} {...control} />}</Field>
      </div>
    </Card>
  );
}

export function GuardSettings() {
  const toast = useToast();
  const saved = useGuardRules();
  const save = useSaveGuardRules();
  const test = useTestGuard();
  const [rules, setRules] = useState<GuardRule[] | null>(null);
  const [sample, setSample] = useState(t("guard.sample"));
  useEffect(() => {
    if (saved.data && !rules) setRules(saved.data.rules);
  }, [saved.data, rules]);
  if (!rules) return <Card title={t("guard.title")}><Skeleton className="h-6 w-full" /></Card>;
  const change = (index: number, changes: Partial<GuardRule>) => setRules(rules.map((rule, i) => (i === index ? { ...rule, ...changes } : rule)));
  return (
    <Card title={t("guard.title")} description={t("guard.description")}>
      <div className="flex flex-col gap-4">
        {rules.map((rule, index) => (
          <fieldset key={index} data-testid="guard-rule" aria-label={rule.name} className="flex flex-col gap-2 rounded-md border border-line-subtle p-3">
            <Switch label={rule.name} checked={rule.enabled ?? true} onChange={(enabled) => change(index, { enabled })} />
            <Segmented label={t("guard.action")} value={rule.action ?? "mask"} options={ACTIONS} onChange={(action) => change(index, { action })} />
            <Field label={t("guard.pattern")}>{({ invalid, ...control }) => <Input className="font-mono" spellCheck={false} invalid={invalid} value={rule.pattern} onChange={(event) => change(index, { pattern: event.target.value })} {...control} />}</Field>
          </fieldset>
        ))}
        <Field label={t("guard.sampleLabel")}>{({ invalid, ...control }) => <Textarea invalid={invalid} rows={2} value={sample} onChange={(event) => setSample(event.target.value)} {...control} />}</Field>
        <div className="flex gap-2">
          <Button loading={test.isPending} onClick={() => test.mutate({ rules, sample })}>{t("guard.test")}</Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate({ rules }, { onSuccess: () => toast({ title: t("guard.saved") }) })}>{t("settings.save")}</Button>
        </div>
        {save.isError ? <ErrorState title={t("guard.saveError")} description={save.error instanceof ApiRequestError ? save.error.detail.message : ""} /> : null}
        {test.data ? (
          <div data-testid="guard-result" className="flex flex-col gap-1 rounded-md bg-surface-sunken p-3 text-md text-ink-primary">
            {(test.data.errors ?? []).map((error) => <p key={error} className="text-status-danger">{error}</p>)}
            <p className="whitespace-pre-wrap break-words font-mono text-sm">{test.data.masked}</p>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

export function UsageSettings() {
  const usage = useUsage();
  const setCap = useSetCap();
  const [cap, setCapText] = useState<string | null>(null);
  if (!usage.data) return <Card title={t("usage.title")}><Skeleton className="h-6 w-full" /></Card>;
  const data = usage.data;
  return (
    <Card title={t("usage.title")} description={t("usage.description")}>
      <div className="flex flex-col gap-3">
        <p data-testid="usage-total" className="text-md tabular-nums text-ink-primary">{t("usage.total", { total: data.total_today.toLocaleString() })}</p>
        {data.near_cap ? <p className="text-md text-status-warning">{t("usage.near")}</p> : null}
        <ul className="flex flex-col gap-1">
          {data.today.map((row) => (
            <li key={row.agent} className="flex justify-between gap-3 text-md tabular-nums text-ink-secondary">
              <span>{row.agent}</span>
              <span>{tn("usage.row", row.calls, { tokens: (row.input_tokens + row.output_tokens).toLocaleString() })}</span>
            </li>
          ))}
        </ul>
        <form
          className="flex flex-col items-start gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            setCap.mutate(Number(cap ?? data.daily_cap));
          }}
        >
          <div className="w-full"><Field label={t("usage.cap")} hint={t("usage.cap.hint")}>{({ invalid, ...control }) => <Input type="number" min={0} invalid={invalid} value={cap ?? data.daily_cap} onChange={(event) => setCapText(event.target.value)} {...control} />}</Field></div>
          <Button type="submit" loading={setCap.isPending}>{t("settings.save")}</Button>
        </form>
      </div>
    </Card>
  );
}

export function NotificationSettings() {
  const quiet = useQuietHours();
  const save = useSaveQuietHours();
  const toast = useToast();
  if (!quiet.data) return <Card title={t("notifications.title")}><Skeleton className="h-6 w-full" /></Card>;
  const value = quiet.data;
  const update = (changes: Partial<QuietHours>) => save.mutate({ ...value, ...changes });
  const allow = () => void Notification.requestPermission().then((result) => toast({ title: t(result === "granted" ? "notifications.allowed" : "notifications.blocked") }));
  return (
    <Card title={t("notifications.title")} description={t("quiet.description")}>
      <div className="flex flex-col gap-4">
        <Switch label={t("quiet.enabled")} checked={value.enabled ?? false} onChange={(enabled) => update({ enabled })} />
        <div className="grid gap-3 md:grid-cols-2">
          <Field label={t("quiet.start")}>{({ invalid, ...control }) => <Input type="time" invalid={invalid} value={value.start ?? "22:00"} onChange={(event) => update({ start: event.target.value })} {...control} />}</Field>
          <Field label={t("quiet.end")}>{({ invalid, ...control }) => <Input type="time" invalid={invalid} value={value.end ?? "07:00"} onChange={(event) => update({ end: event.target.value })} {...control} />}</Field>
        </div>
        <Field label={t("quiet.limit")}>{({ invalid, ...control }) => <Input type="number" min={0} invalid={invalid} value={value.channel_daily_limit ?? 20} onChange={(event) => update({ channel_daily_limit: Number(event.target.value) })} {...control} />}</Field>
        <div><Button onClick={allow}>{t("notifications.allow")}</Button></div>
      </div>
    </Card>
  );
}
