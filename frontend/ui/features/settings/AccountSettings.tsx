"use client";

import { useEffect, useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { MailProfile } from "@/ui/client/contracts.generated";
import { useMailAccounts, useMailStatus, useRemoveAccount, useSaveAccount, useTestAccount } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { Segmented } from "@/ui/primitives/Segmented";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { Switch } from "@/ui/primitives/Switch";
import { t } from "@/ui/strings";

const GMAIL = { imapHost: "imap.gmail.com", imapPort: "993", smtpHost: "smtp.gmail.com", smtpPort: "465", secure: true };
const OTHER = { imapHost: "", imapPort: "993", smtpHost: "", smtpPort: "465", secure: true };

const messageOf = (error: unknown) => (error instanceof ApiRequestError ? error.detail.message : t("settings.models.error"));

const nameFor = (email: string) => email.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "mail";

const STATES: Readonly<Record<string, { tone: "done" | "running" | "failed" | "idle"; label: "accounts.state.live" | "accounts.state.syncing" | "accounts.state.offline" | "accounts.state.failed" | "accounts.state.off" }>> = {
  live: { tone: "done", label: "accounts.state.live" },
  connecting: { tone: "running", label: "accounts.state.syncing" },
  syncing: { tone: "running", label: "accounts.state.syncing" },
  backfilling: { tone: "running", label: "accounts.state.syncing" },
  offline: { tone: "failed", label: "accounts.state.offline" },
  failed: { tone: "failed", label: "accounts.state.failed" },
  off: { tone: "idle", label: "accounts.state.off" },
};

export function AccountSettings() {
  const accounts = useMailAccounts();
  const status = useMailStatus();
  const remove = useRemoveAccount();
  const save = useSaveAccount();
  const test = useTestAccount();
  const [editing, setEditing] = useState(false);
  const [kind, setKind] = useState<"gmail" | "other">("gmail");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [servers, setServers] = useState(GMAIL);

  const active = accounts.data?.accounts.find((account) => account.name === accounts.data?.active);
  useEffect(() => {
    setServers(kind === "gmail" ? GMAIL : OTHER);
  }, [kind]);

  const profile = (): MailProfile => ({
    label: kind === "gmail" ? t("accounts.kind.gmail") : email,
    imap: { host: servers.imapHost, port: Number(servers.imapPort), secure: servers.secure },
    smtp: { host: servers.smtpHost, port: Number(servers.smtpPort), secure: servers.secure },
    auth: { type: "password", user: email.trim() },
    mailboxes: ["INBOX"],
  });
  const ready = email.includes("@") && servers.imapHost && servers.smtpHost && password;
  const state = STATES[status.data?.state ?? "off"] ?? STATES.off;

  if (accounts.isPending) return <Card title={t("settings.section.accounts")}><Skeleton className="h-6 w-full" /></Card>;
  if (accounts.isError) return <Card title={t("settings.section.accounts")}><ErrorState title={t("accounts.error")} onRetry={() => void accounts.refetch()} /></Card>;

  return (
    <Card title={t("settings.section.accounts")} description={t("accounts.description")}>
      <div className="flex flex-col gap-4">
        {active && !editing ? (
          <div className="flex flex-col items-start gap-3">
            <p className="break-all text-md text-ink-primary">{active.profile.auth.user}</p>
            <p role="status" data-testid="mail-state" className="flex items-center gap-2 text-md text-ink-secondary">
              {state ? <StatusDot tone={state.tone} /> : null}
              {status.data?.message ?? (state ? t(state.label) : "")}
            </p>
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
              save.mutate({ name: nameFor(email), profile: profile(), password }, { onSuccess: () => setEditing(false) });
            }}
          >
            <Segmented label={t("accounts.kind")} value={kind} options={[{ value: "gmail", label: t("accounts.kind.gmail") }, { value: "other", label: t("accounts.kind.other") }]} onChange={setKind} />
            <Field label={t("accounts.email")}>{({ invalid, ...control }) => <Input type="email" autoComplete="off" spellCheck={false} invalid={invalid} value={email} onChange={(event) => setEmail(event.target.value)} {...control} />}</Field>
            <Field label={t("accounts.password")} hint={kind === "gmail" ? t("accounts.password.gmail") : t("accounts.password.hint")}>{({ invalid, ...control }) => <Input type="password" autoComplete="off" invalid={invalid} value={password} onChange={(event) => setPassword(event.target.value)} {...control} />}</Field>
            {kind === "other" ? (
              <div className="grid gap-3 md:grid-cols-2">
                <Field label={t("accounts.imapHost")}>{({ invalid, ...control }) => <Input spellCheck={false} invalid={invalid} value={servers.imapHost} onChange={(event) => setServers({ ...servers, imapHost: event.target.value })} {...control} />}</Field>
                <Field label={t("accounts.imapPort")}>{({ invalid, ...control }) => <Input inputMode="numeric" invalid={invalid} value={servers.imapPort} onChange={(event) => setServers({ ...servers, imapPort: event.target.value })} {...control} />}</Field>
                <Field label={t("accounts.smtpHost")}>{({ invalid, ...control }) => <Input spellCheck={false} invalid={invalid} value={servers.smtpHost} onChange={(event) => setServers({ ...servers, smtpHost: event.target.value })} {...control} />}</Field>
                <Field label={t("accounts.smtpPort")}>{({ invalid, ...control }) => <Input inputMode="numeric" invalid={invalid} value={servers.smtpPort} onChange={(event) => setServers({ ...servers, smtpPort: event.target.value })} {...control} />}</Field>
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
            {test.isError ? <ErrorState title={t("accounts.testFailed")} description={messageOf(test.error)} /> : null}
            {save.isError ? <ErrorState title={t("accounts.saveFailed")} description={messageOf(save.error)} /> : null}
            <div className="flex flex-wrap gap-2">
              <Button loading={test.isPending} disabled={!ready} onClick={() => test.mutate({ profile: profile(), password })}>{t("accounts.test")}</Button>
              <Button type="submit" variant="primary" loading={save.isPending} disabled={!ready}>{t("accounts.connect")}</Button>
              {active ? <Button variant="quiet" onClick={() => setEditing(false)}>{t("home.picker.cancel")}</Button> : null}
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}
