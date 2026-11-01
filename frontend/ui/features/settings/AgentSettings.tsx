"use client";

import { useEffect, useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { GuardRule, Permissions, QuietHours, SendCheckSettings } from "@/ui/client/contracts.generated";
import { usePermissions, useSavePermissions } from "@/ui/client/sessions";
import { useGuardRules, useQuietHours, useSaveGuardRules, useSaveQuietHours, useSaveSendChecks, useSendChecks, useSetCap, useTestGuard, useToolCatalog, useUsage } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { SettingRow } from "@/ui/primitives/SettingRow";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Switch } from "@/ui/primitives/Switch";
import { useToast } from "@/ui/primitives/Toast";
import { t, tn } from "@/ui/strings";

type Level = NonNullable<Permissions["command"]>;
type CheckLevel = NonNullable<SendCheckSettings["newer_reply"]>;

const LEVEL_OPTIONS = [
  { value: "allow", label: t("permissions.allow") },
  { value: "ask", label: t("permissions.ask") },
  { value: "off", label: t("permissions.off") },
];
const ALWAYS_ASKS = LEVEL_OPTIONS.filter((option) => option.value !== "allow");

export function PermissionsSettings() {
  const permissions = usePermissions();
  const catalog = useToolCatalog();
  const save = useSavePermissions();
  const [folder, setFolder] = useState("");
  if (permissions.isPending || catalog.isPending) return <Card title={t("permissions.title")}><Skeleton className="h-6 w-full" /></Card>;
  if (permissions.isError || catalog.isError) return <Card title={t("permissions.title")}><ErrorState title={t("permissions.error")} onRetry={() => void permissions.refetch()} /></Card>;
  const value = permissions.data;
  const update = (changes: Partial<Permissions>) => save.mutate({ ...value, ...changes });
  const folders = value.folders ?? [];
  const groups = [...new Set(catalog.data.tools.map((tool) => tool.group))];
  return (
    <div className="flex flex-col gap-5">
      <Card title={t("permissions.title")} description={t("permissions.description")}>
        <div className="flex flex-col gap-5">
          {groups.map((group) => (
            <div key={group}>
              <h3 className="mb-2 text-sm text-ink-muted">{group}</h3>
              {catalog.data.tools
                .filter((tool) => tool.group === group)
                .map((tool) => (
                  <SettingRow key={tool.name} label={tool.label} description={tool.description}>
                    <Select compact label={tool.label} value={tool.level} options={tool.can_allow ? LEVEL_OPTIONS : ALWAYS_ASKS} onChange={(level) => update({ tools: { ...value.tools, [tool.name]: level as Level } })} />
                  </SettingRow>
                ))}
            </div>
          ))}
        </div>
      </Card>
      <Card title={t("permissions.safety")} description={t("permissions.untrustedNote")}>
        <SettingRow label={t("permissions.full")} description={t("permissions.commandsNote")}>
          <div className="flex justify-end">
            <Switch label={t("permissions.full")} hideLabel checked={value.full_computer_access ?? false} onChange={(full_computer_access) => update({ full_computer_access })} />
          </div>
        </SettingRow>
        <form
          className="mt-3 flex items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            update({ folders: [...folders, folder.trim()] });
            setFolder("");
          }}
        >
          <div className="min-w-0 flex-1"><Field label={t("permissions.addFolder")}>{({ invalid, ...control }) => <Input invalid={invalid} spellCheck={false} value={folder} onChange={(event) => setFolder(event.target.value)} {...control} />}</Field></div>
          <Button type="submit" disabled={!folder.trim()}>{t("memory.addAction")}</Button>
        </form>
        {folders.length ? (
          <ul className="mt-2 flex flex-col gap-1">
            {folders.map((item) => (
              <li key={item} className="flex items-center justify-between gap-2 text-md text-ink-secondary">
                <span className="min-w-0 break-all font-mono text-sm">{item}</span>
                <IconButton icon="close" label={t("tasks.remove", { title: item })} onClick={() => update({ folders: folders.filter((entry) => entry !== item) })} />
              </li>
            ))}
          </ul>
        ) : null}
      </Card>
    </div>
  );
}

const CHECK_OPTIONS = [
  { value: "off", label: t("permissions.off") },
  { value: "warn", label: t("checks.warn") },
  { value: "block", label: t("checks.block") },
];

export function SendCheckSettingsCard() {
  const checks = useSendChecks();
  const save = useSaveSendChecks();
  if (!checks.data) return <Card title={t("checks.title")}><Skeleton className="h-6 w-full" /></Card>;
  const value = checks.data;
  const update = (changes: Partial<SendCheckSettings>) => save.mutate({ ...value, ...changes });
  return (
    <Card title={t("checks.title")} description={t("checks.description")}>
      <SettingRow label={t("checks.external")}>
        <Select compact label={t("checks.external")} value={value.external_recipient ?? "warn"} options={CHECK_OPTIONS} onChange={(level) => update({ external_recipient: level as CheckLevel })} />
      </SettingRow>
      <SettingRow label={t("checks.attachment")}>
        <Select compact label={t("checks.attachment")} value={value.missing_attachment ?? "warn"} options={CHECK_OPTIONS} onChange={(level) => update({ missing_attachment: level as CheckLevel })} />
      </SettingRow>
      <SettingRow label={t("checks.newer")}>
        <Select compact label={t("checks.newer")} value={value.newer_reply ?? "warn"} options={CHECK_OPTIONS} onChange={(level) => update({ newer_reply: level as CheckLevel })} />
      </SettingRow>
      <SettingRow label={t("checks.undo")}>
        <Input className="py-1" aria-label={t("checks.undo")} type="number" min={0} max={60} value={value.undo_seconds ?? 5} onChange={(event) => update({ undo_seconds: Number(event.target.value) })} />
      </SettingRow>
    </Card>
  );
}

const ACTION_OPTIONS = [
  { value: "mask", label: t("guard.mask") },
  { value: "block", label: t("checks.block") },
];

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
          <fieldset key={index} data-testid="guard-rule" aria-label={rule.name} className="border-b border-line-subtle pb-3">
            <div className="flex items-center gap-3">
              <span className="min-w-0 flex-1 text-md text-ink-primary">{rule.name}</span>
              <div className="w-rail-wide shrink-0">
                <Select compact label={t("guard.action")} value={rule.action ?? "mask"} options={ACTION_OPTIONS} onChange={(action) => change(index, { action: action as GuardRule["action"] })} />
              </div>
              <Switch label={rule.name} hideLabel checked={rule.enabled ?? true} onChange={(enabled) => change(index, { enabled })} />
            </div>
            <details className="mt-1 text-sm text-ink-muted">
              <summary className="focus-ring cursor-pointer rounded-sm">{t("guard.pattern")}</summary>
              <div className="mt-2">
                <Input aria-label={t("guard.pattern")} className="font-mono" spellCheck={false} value={rule.pattern} onChange={(event) => change(index, { pattern: event.target.value })} />
              </div>
            </details>
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
      <SettingRow label={t("quiet.enabled")}>
        <div className="flex justify-end"><Switch label={t("quiet.enabled")} hideLabel checked={value.enabled ?? false} onChange={(enabled) => update({ enabled })} /></div>
      </SettingRow>
      <SettingRow label={t("quiet.start")}>
        <Input className="py-1" aria-label={t("quiet.start")} type="time" value={value.start ?? "22:00"} onChange={(event) => update({ start: event.target.value })} />
      </SettingRow>
      <SettingRow label={t("quiet.end")}>
        <Input className="py-1" aria-label={t("quiet.end")} type="time" value={value.end ?? "07:00"} onChange={(event) => update({ end: event.target.value })} />
      </SettingRow>
      <SettingRow label={t("quiet.limit")}>
        <Input className="py-1" aria-label={t("quiet.limit")} type="number" min={0} value={value.channel_daily_limit ?? 20} onChange={(event) => update({ channel_daily_limit: Number(event.target.value) })} />
      </SettingRow>
      <SettingRow label={t("notifications.browser")} description={t("notifications.browser.description")}>
        <div className="flex justify-end"><Button onClick={allow}>{t("notifications.allow")}</Button></div>
      </SettingRow>
    </Card>
  );
}
