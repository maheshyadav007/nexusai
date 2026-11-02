"use client";

import { useEffect, useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { MailProfile } from "@/ui/client/contracts.generated";
import { useMailAccounts, useMailPresets, useMailStatus, useProbeServer, useRemoveAccount, useSaveAccount, useTestAccount } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Progress } from "@/ui/primitives/Progress";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { Switch } from "@/ui/primitives/Switch";
import { t } from "@/ui/strings";

const BLANK = { imapHost: "", imapPort: "993", smtpHost: "", smtpPort: "465", secure: true };
// A company's own server is listed under this, for logins with no @ in them.
const ANY_LOGIN = "*";

const messageOf = (error: unknown) => (error instanceof ApiRequestError ? error.detail.message : t("settings.models.error"));

const nameFor = (login: string) => login.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "mail";

const STATES: Readonly<Record<string, { tone: "done" | "running" | "failed" | "idle"; label: "accounts.state.live" | "accounts.state.syncing" | "accounts.state.offline" | "accounts.state.failed" | "accounts.state.off" }>> = {
  live: { tone: "done", label: "accounts.state.live" },
  connecting: { tone: "running", label: "accounts.state.syncing" },
  syncing: { tone: "running", label: "accounts.state.syncing" },
  backfilling: { tone: "running", label: "accounts.state.syncing" },
  offline: { tone: "failed", label: "accounts.state.offline" },
  failed: { tone: "failed", label: "accounts.state.failed" },
  off: { tone: "idle", label: "accounts.state.off" },
};

/** Fetching mail carries on in the background, so nobody has to wait here for it. */
function MailDownload() {
  const status = useMailStatus();
  const total = status.data?.total ?? 0;
  if (!total) return null;
  const done = status.data?.done ?? 0;
  return (
    <div data-testid="mail-download" className="flex w-full flex-col gap-1">
      <Progress label={t("accounts.download")} value={done} max={total} />
      <p className="text-sm tabular-nums text-ink-muted">{t("accounts.download.count", { done, total })}</p>
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

  const active = accounts.data?.accounts.find((account) => account.name === accounts.data?.active);
  const domain = login.includes("@") ? (login.split("@").pop() ?? "").trim().toLowerCase() : ANY_LOGIN;
  const preset = presets.data?.presets.find((row) => row.domain === domain);
  useEffect(() => {
    if (preset) setServers({ imapHost: preset.imap_host, imapPort: String(preset.imap_port), smtpHost: preset.smtp_host, smtpPort: String(preset.smtp_port), secure: preset.secure ?? true });
  }, [preset]);

  const server = servers.imapHost.trim();
  const profileWith = (found: typeof servers): MailProfile => {
    const from = address.trim() || addressFor(login, found.imapHost);
    return {
      label: preset?.label ?? found.imapHost.trim(),
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
  const state = STATES[status.data?.state ?? "off"] ?? STATES.off;

  if (accounts.isPending) return <Card title={t("accounts.title")}><Skeleton className="h-6 w-full" /></Card>;
  if (accounts.isError) return <Card title={t("accounts.title")}><ErrorState title={t("accounts.error")} onRetry={() => void accounts.refetch()} /></Card>;

  return (
    <Card title={t("accounts.title")} description={t("accounts.description")}>
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
              void settled().then((found) => save.mutate({ name: nameFor(login), profile: profileWith(found), password }, { onSuccess: () => setEditing(false) }));
            }}
          >
            <Field label={t("accounts.server")} hint={t("accounts.server.hint")}>{({ invalid, ...control }) => <Input autoComplete="off" spellCheck={false} placeholder={t("accounts.server.placeholder")} invalid={invalid} value={servers.imapHost} onChange={(event) => setServers({ ...servers, imapHost: event.target.value })} {...control} />}</Field>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label={t("accounts.username")} hint={t("accounts.username.hint")}>{({ invalid, ...control }) => <Input autoComplete="off" spellCheck={false} invalid={invalid} value={login} onChange={(event) => setLogin(event.target.value)} {...control} />}</Field>
              <Field label={t("accounts.password")} hint={preset?.password_hint ?? t("accounts.password.hint")}>{({ invalid, ...control }) => <Input type="password" autoComplete="off" invalid={invalid} value={password} onChange={(event) => setPassword(event.target.value)} {...control} />}</Field>
            </div>
            <div>
              <Button variant="quiet" aria-expanded={details} onClick={() => setDetails(!details)}>{t(details ? "accounts.servers.hide" : "accounts.servers.show")}</Button>
            </div>
            {details ? (
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
            {probe.isError ? <ErrorState title={t("accounts.server.invalid")} /> : null}
            {test.isError ? <ErrorState title={t("accounts.testFailed")} description={messageOf(test.error)} /> : null}
            {save.isError ? <ErrorState title={t("accounts.saveFailed")} description={messageOf(save.error)} /> : null}
            <div className="flex flex-wrap gap-2">
              <Button loading={test.isPending || probe.isPending} disabled={!ready} onClick={() => void settled().then((found) => test.mutate({ profile: profileWith(found), password }))}>{t("accounts.test")}</Button>
              <Button type="submit" variant="primary" loading={save.isPending} disabled={!ready}>{t("accounts.connect")}</Button>
              {active ? <Button variant="quiet" onClick={() => setEditing(false)}>{t("home.picker.cancel")}</Button> : null}
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}
