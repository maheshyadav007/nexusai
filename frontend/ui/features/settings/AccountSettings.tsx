"use client";

import { useEffect, useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { MailProfile } from "@/ui/client/contracts.generated";
import { useMailAccounts, useMailPresets, useMailStatus, useProbeServer, useRemoveAccount, useSaveAccount, useSetNeverDelete, useTestAccount } from "@/ui/client/mail";
import { usePipelines } from "@/ui/client/work";
import { PipelineRow } from "@/ui/features/cockpit/Pipelines";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Progress } from "@/ui/primitives/Progress";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { Switch } from "@/ui/primitives/Switch";
import { t, type StringKey } from "@/ui/strings";

const MAIL_PIPELINE = "mail-sync";
// A few are enough to show what's there. Gmail can have dozens of labels.
const FOLDERS_SHOWN = 4;
const BLANK = { imapHost: "", imapPort: "993", smtpHost: "", smtpPort: "465", secure: true };
// A company's own server is listed under this, for logins with no @ in them.
const ANY_LOGIN = "*";

const messageOf = (error: unknown) => (error instanceof ApiRequestError ? error.detail.message : t("settings.models.error"));

const nameFor = (login: string) => login.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "mail";

const STATES: Readonly<Record<string, { tone: "done" | "running" | "failed" | "idle"; label: StringKey }>> = {
  live: { tone: "done", label: "accounts.state.live" },
  connecting: { tone: "running", label: "accounts.state.syncing" },
  syncing: { tone: "running", label: "accounts.state.syncing" },
  backfilling: { tone: "running", label: "accounts.state.syncing" },
  offline: { tone: "failed", label: "accounts.state.offline" },
  failed: { tone: "failed", label: "accounts.state.failed" },
  off: { tone: "idle", label: "accounts.state.off" },
  paused: { tone: "idle", label: "accounts.state.paused" },
};

/** Fetching mail carries on in the background, so nobody has to wait here for it. */
function MailDownload() {
  const status = useMailStatus();
  const total = status.data?.total ?? 0;
  if (!total) return null;
  const done = status.data?.done ?? 0;
  return (
    <div data-testid="mail-download" className="flex w-full flex-col gap-1">
      <p className="text-sm text-ink-secondary">{t("accounts.download.continue")}</p>
      <Progress label={t("accounts.download")} value={done} max={total} />
      <p className="text-sm tabular-nums text-ink-muted">{t("accounts.download.count", { done, total })}</p>
    </div>
  );
}

/** The same controls as the Schedules page and the Cockpit, plus the promise about the server. */
function MailSyncControls() {
  const pipelines = usePipelines();
  const status = useMailStatus();
  const neverDelete = useSetNeverDelete();
  const row = pipelines.data?.pipelines.find((item) => item.id === MAIL_PIPELINE);
  return (
    <div className="flex w-full flex-col gap-3">
      {row ? <ul><PipelineRow row={row} /></ul> : null}
      <Switch label={t("accounts.neverDelete")} checked={status.data?.never_delete ?? true} onChange={(value) => neverDelete.mutate(value)} />
      <p className="text-sm text-ink-muted">{t("accounts.neverDelete.hint")}</p>
    </div>
  );
}

/** Where a company login with no @ most likely sends from: mail.company.com gives company.com. */
function addressFor(login: string, server: string): string {
  const clean = login.trim();
  if (clean.includes("@") || !clean) return "";
  const parts = server.trim().split(".");
  return parts.length > 2 && !/^[0-9.]+$/.test(server) ? `${clean}@${parts.slice(1).join(".")}` : "";
}

export function AccountSettings() {
  const accounts = useMailAccounts();
  const status = useMailStatus();
  const presets = useMailPresets();
  const remove = useRemoveAccount();
  const save = useSaveAccount();
  const test = useTestAccount();
  const probe = useProbeServer();
  const [editing, setEditing] = useState(false);
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [address, setAddress] = useState("");
  const [servers, setServers] = useState(BLANK);
  const [details, setDetails] = useState(false);
  const [pull, setPull] = useState("");

  const active = accounts.data?.accounts.find((account) => account.name === accounts.data?.active);
  const domain = login.includes("@") ? (login.split("@").pop() ?? "").trim().toLowerCase() : ANY_LOGIN;
  // A system server takes any login that no other preset claims, and hides the server details.
  const preset = presets.data?.presets.find((row) => row.domain === domain) ?? presets.data?.presets.find((row) => row.domain === ANY_LOGIN);
  const managed = presets.data?.presets.some((row) => row.system) ?? false;
  useEffect(() => {
    if (preset) setServers({ imapHost: preset.imap_host, imapPort: String(preset.imap_port), smtpHost: preset.smtp_host, smtpPort: String(preset.smtp_port), secure: preset.secure ?? true });
  }, [preset]);

  const server = servers.imapHost.trim();
  const profileWith = (found: typeof servers): MailProfile => {
    const company = preset?.address_domain;
    const from = address.trim() || (company && !login.includes("@") ? `${login.trim()}@${company}` : addressFor(login, found.imapHost));
    return {
      label: preset?.label ?? found.imapHost.trim(),
      protocol: preset?.protocol ?? "imap",
      system: preset?.system ?? false,
      imap: { host: found.imapHost.trim(), port: Number(found.imapPort), secure: found.secure },
      smtp: { host: (found.smtpHost || found.imapHost).trim(), port: Number(found.smtpPort), secure: found.secure },
      auth: { type: "password", user: login.trim() },
      mailboxes: ["INBOX"],
      ...(from ? { address: from } : {}),
    };
  };
  // Unless the details are open or known, the rest is worked out from the server name.
  const settled = async (): Promise<typeof servers> => {
    if (details || preset) return servers;
    const found = await probe.mutateAsync(server);
    const next = { ...servers, imapPort: String(found.imap_port), smtpHost: found.smtp_host, smtpPort: String(found.smtp_port) };
    setServers(next);
    return next;
  };
  const ready = login.trim() && password && server;
  // What the server holds has to be known before anyone can choose how much of it to download.
  const reached = test.data?.results.find((result) => result.service === "imap")?.ok === true;
  const counts = reached ? (test.data?.counts ?? []) : [];
  const onServer = reached ? (test.data?.total ?? 0) : 0;
  const biggest = counts.filter((row) => row.messages > 0).sort((a, b) => b.messages - a.messages).slice(0, FOLDERS_SHOWN);
  const wanted = Number(pull);
  const canStart = onServer === 0 || (Number.isInteger(wanted) && wanted >= 1);
  const { reset: forgetTest } = test;
  // A different login or server may hold different mail, so that's asked again.
  useEffect(() => forgetTest(), [forgetTest, login, password, servers.imapHost]);
  const suggested = test.data?.suggested_pull;
  useEffect(() => {
    if (suggested !== undefined) setPull(String(suggested));
  }, [suggested]);
  const state = STATES[status.data?.state ?? "off"] ?? STATES.off;

  if (accounts.isPending) return <Card title={t("accounts.title")}><Skeleton className="h-6 w-full" /></Card>;
  if (accounts.isError) return <Card title={t("accounts.title")}><ErrorState title={t("accounts.error")} onRetry={() => void accounts.refetch()} /></Card>;

  return (
    <Card title={t("accounts.title")} description={t(managed ? "accounts.description.system" : "accounts.description")}>
      <div className="flex flex-col gap-4">
        {active && !editing ? (
          <div className="flex flex-col items-start gap-3">
            <p className="break-all text-md text-ink-primary">{active.profile.address ?? active.profile.auth.user}</p>
            <p role="status" data-testid="mail-state" className="flex items-center gap-2 text-md text-ink-secondary">
              {state ? <StatusDot tone={state.tone} /> : null}
              {status.data?.message ?? (state ? t(state.label) : "")}
            </p>
            <MailDownload />
            <p className="text-sm tabular-nums text-ink-muted">{t("accounts.count", { count: status.data?.messages ?? 0 })}</p>
            <MailSyncControls />
            {!active.has_password ? <p className="text-md text-status-warning">{t("accounts.noPassword")}</p> : null}
            <div className="flex gap-2">
              <Button onClick={() => setEditing(true)}>{t("accounts.change")}</Button>
              <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate(active.name)}>{t("accounts.remove")}</Button>
            </div>
          </div>
        ) : (
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (!reached) {
                void settled().then((found) => test.mutate({ profile: profileWith(found), password }));
                return;
              }
              void settled().then((found) => save.mutate({ name: nameFor(login), profile: profileWith(found), password, pull_limit: onServer && wanted < onServer ? wanted : null }, { onSuccess: () => setEditing(false) }));
            }}
          >
            {managed ? null : <Field label={t("accounts.server")} hint={t("accounts.server.hint")}>{({ invalid, ...control }) => <Input autoComplete="off" spellCheck={false} placeholder={t("accounts.server.placeholder")} invalid={invalid} value={servers.imapHost} onChange={(event) => setServers({ ...servers, imapHost: event.target.value })} {...control} />}</Field>}
            <div className="grid gap-3 md:grid-cols-2">
              <Field label={t("accounts.username")} hint={t("accounts.username.hint")}>{({ invalid, ...control }) => <Input autoComplete="off" spellCheck={false} invalid={invalid} value={login} onChange={(event) => setLogin(event.target.value)} {...control} />}</Field>
              <Field label={t("accounts.password")} hint={preset?.password_hint ?? t("accounts.password.hint")}>{({ invalid, ...control }) => <Input type="password" autoComplete="off" invalid={invalid} value={password} onChange={(event) => setPassword(event.target.value)} {...control} />}</Field>
            </div>
            {managed ? null : (
              <div>
                <Button variant="quiet" aria-expanded={details} onClick={() => setDetails(!details)}>{t(details ? "accounts.servers.hide" : "accounts.servers.show")}</Button>
              </div>
            )}
            {details && !managed ? (
              <div className="grid gap-3 md:grid-cols-2">
                <Field label={t("accounts.imapPort")}>{({ invalid, ...control }) => <Input inputMode="numeric" invalid={invalid} value={servers.imapPort} onChange={(event) => setServers({ ...servers, imapPort: event.target.value })} {...control} />}</Field>
                <Field label={t("accounts.smtpHost")} hint={t("accounts.smtpHost.hint")}>{({ invalid, ...control }) => <Input spellCheck={false} invalid={invalid} value={servers.smtpHost} onChange={(event) => setServers({ ...servers, smtpHost: event.target.value })} {...control} />}</Field>
                <Field label={t("accounts.smtpPort")}>{({ invalid, ...control }) => <Input inputMode="numeric" invalid={invalid} value={servers.smtpPort} onChange={(event) => setServers({ ...servers, smtpPort: event.target.value })} {...control} />}</Field>
                <Field label={t("accounts.email")} hint={t("accounts.email.hint")}>{({ invalid, ...control }) => <Input type="email" autoComplete="off" spellCheck={false} placeholder={addressFor(login, server)} invalid={invalid} value={address} onChange={(event) => setAddress(event.target.value)} {...control} />}</Field>
                <Switch label={t("accounts.secure")} checked={servers.secure} onChange={(secure) => setServers({ ...servers, secure })} />
              </div>
            ) : null}
            {test.data ? (
              <ul data-testid="connection-results" className="flex flex-col gap-1">
                {test.data.results.map((result) => (
                  <li key={result.service} className="flex items-center gap-2 text-md text-ink-secondary">
                    <StatusDot tone={result.ok ? "done" : "failed"} />
                    {t(result.service === "imap" ? "accounts.imap" : "accounts.smtp")}: {result.message}
                  </li>
                ))}
              </ul>
            ) : null}
            {onServer ? (
              <div data-testid="pull-chooser" className="flex flex-col gap-3">
                <div>
                  <p className="text-md tabular-nums text-ink-primary">{t("accounts.onServer", { total: onServer.toLocaleString() })}</p>
                  <p className="text-sm tabular-nums text-ink-muted">{t("accounts.onServer.folders", { count: counts.length, folders: biggest.map((row) => `${row.role === "inbox" ? t("nav.inbox") : (row.name.split("/").pop() ?? row.name)} ${row.messages.toLocaleString()}`).join(", ") })}</p>
                </div>
                <div className="flex flex-wrap items-end gap-2">
                  <div className="w-48">
                    <Field label={t("accounts.pull")} hint={t("accounts.pull.hint")}>{({ invalid, ...control }) => <Input type="number" min={1} max={onServer} invalid={invalid} value={pull} onChange={(event) => setPull(event.target.value)} {...control} />}</Field>
                  </div>
                  <Button variant="quiet" onClick={() => setPull(String(onServer))}>{t("accounts.pull.all", { total: onServer.toLocaleString() })}</Button>
                </div>
              </div>
            ) : null}
            {probe.isError ? <ErrorState title={t("accounts.server.invalid")} /> : null}
            {test.isError ? <ErrorState title={t("accounts.testFailed")} description={messageOf(test.error)} /> : null}
            {save.isError ? <ErrorState title={t("accounts.saveFailed")} description={messageOf(save.error)} /> : null}
            <div className="flex flex-wrap gap-2">
              <Button type="submit" variant="primary" loading={save.isPending || test.isPending || probe.isPending} disabled={!ready || (reached && !canStart)}>{t(reached ? "accounts.start" : "accounts.connect")}</Button>
              {active ? <Button variant="quiet" onClick={() => setEditing(false)}>{t("home.picker.cancel")}</Button> : null}
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}
