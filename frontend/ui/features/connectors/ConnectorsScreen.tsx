"use client";

import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { useAddConnector, useApproveConnector, useConnectors, useRefreshConnector, useRemoveConnector, useSetConnectorEnabled, useTestConnector } from "@/ui/client/connectors";
import type { AddConnector, Connector, ConnectorTool } from "@/ui/client/contracts.generated";
import { usePermissions, useSavePermissions } from "@/ui/client/sessions";
import { PstImportCard } from "@/ui/features/mail/PstImportCard";
import { AccountSettings } from "@/ui/features/settings/AccountSettings";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { Dialog } from "@/ui/primitives/Dialog";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { PageHeader } from "@/ui/primitives/PageHeader";
import { Segmented } from "@/ui/primitives/Segmented";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { Switch } from "@/ui/primitives/Switch";
import { t, tn, type StringKey } from "@/ui/strings";

type Audience = AddConnector["audience"];
type Level = "allow" | "ask" | "off";

const TONES = { ok: "done", failed: "failed", changed: "waiting", off: "idle" } as const;
const STATE_LABEL: Readonly<Record<string, StringKey>> = {
  ok: "connectors.state.ok",
  failed: "connectors.state.failed",
  changed: "connectors.state.changed",
  off: "connectors.state.off",
};
const INSECURE = "http://";

/** The mail account and old mail together. Setup and the Connectors page both show this. */
export function EmailConnector() {
  return (
    <div className="flex flex-col gap-4">
      <AccountSettings />
      <PstImportCard />
    </div>
  );
}

function ToolRow({ tool }: { tool: ConnectorTool }) {
  const permissions = usePermissions();
  const save = useSavePermissions();
  const options = [
    { value: "ask", label: t("permissions.ask") },
    { value: "allow", label: t("permissions.allow") },
    { value: "off", label: t("permissions.off") },
  ];
  const value = (permissions.data?.tools?.[tool.id] ?? "ask") as Level;
  return (
    <li data-testid="connector-tool" className="flex items-center justify-between gap-4 border-b border-line-subtle py-2 last:border-b-0">
      <span className="flex min-w-0 flex-col">
        <span className="text-md text-ink-primary">{tool.name}</span>
        {tool.description ? <span className="break-words text-sm text-ink-muted">{tool.description}</span> : null}
      </span>
      <div className="w-rail-wide shrink-0">
        <Select label={t("connectors.tool.level", { name: tool.name })} value={value} options={options} onChange={(level) => permissions.data && save.mutate({ ...permissions.data, tools: { ...permissions.data.tools, [tool.id]: level as Level } })} />
      </div>
    </li>
  );
}

function ServerRow({ connector }: { connector: Connector }) {
  const refresh = useRefreshConnector();
  const approve = useApproveConnector();
  const remove = useRemoveConnector();
  const enable = useSetConnectorEnabled();
  const tools = connector.tools ?? [];
  const state = connector.state;
  return (
    <ExpandRow
      label={t("connectors.open", { name: connector.name })}
      testid="connector"
      leading={<StatusDot tone={TONES[state]} />}
      title={connector.name}
      meta={`${t(STATE_LABEL[state] ?? "connectors.state.ok")} · ${tn("connectors.tools", tools.length)} · ${t(connector.audience === "public" ? "connectors.audience.public" : "connectors.audience.internal")}`}
      aside={<Switch label={t("connectors.enabled", { name: connector.name })} hideLabel checked={connector.enabled ?? true} onChange={(enabled) => enable.mutate({ id: connector.id, enabled })} />}
      defaultOpen={state === "changed"}
    >
      <div className="flex flex-col gap-3">
        <p className="break-all text-sm text-ink-muted">{connector.url}</p>
        {connector.detail ? <p data-testid="connector-detail" className="text-md text-ink-secondary">{connector.detail}</p> : null}
        {state === "changed" ? <div><Button variant="primary" loading={approve.isPending} onClick={() => approve.mutate(connector.id)}>{t("connectors.approve")}</Button></div> : null}
        <ul className="flex flex-col">
          {tools.map((tool) => (
            <ToolRow key={tool.id} tool={tool} />
          ))}
        </ul>
        <div className="flex gap-2">
          <Button loading={refresh.isPending} onClick={() => refresh.mutate(connector.id)}>{t("connectors.refresh")}</Button>
          <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate(connector.id)}>{t("connectors.remove")}</Button>
        </div>
      </div>
    </ExpandRow>
  );
}

function AddServer() {
  const test = useTestConnector();
  const add = useAddConnector();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [audience, setAudience] = useState<Audience>("internal");
  const input = { url: url.trim(), ...(token ? { token } : {}) };
  const reset = () => {
    setName("");
    setUrl("");
    setToken("");
    test.reset();
    add.reset();
  };
  return (
    <Dialog
      title={t("connectors.add")}
      description={t("connectors.add.description")}
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
      trigger={<Button variant="primary">{t("connectors.add")}</Button>}
    >
      <form
        className="flex max-h-dialog flex-col gap-3 overflow-y-auto"
        onSubmit={(event) => {
          event.preventDefault();
          add.mutate({ name: name.trim(), audience, ...input }, { onSuccess: () => { setOpen(false); reset(); } });
        }}
      >
        <Field label={t("connectors.name")}>{({ invalid, ...control }) => <Input invalid={invalid} value={name} onChange={(event) => setName(event.target.value)} {...control} />}</Field>
        <Field label={t("connectors.url")} {...(url.startsWith(INSECURE) ? { hint: t("connectors.url.insecure") } : {})}>{({ invalid, ...control }) => <Input spellCheck={false} placeholder={t("connectors.url.placeholder")} invalid={invalid} value={url} onChange={(event) => setUrl(event.target.value)} {...control} />}</Field>
        <Field label={t("connectors.token")} hint={t("connectors.token.hint")}>{({ invalid, ...control }) => <Input type="password" autoComplete="off" invalid={invalid} value={token} onChange={(event) => setToken(event.target.value)} {...control} />}</Field>
        <Segmented label={t("connectors.audience")} value={audience} options={[{ value: "internal", label: t("connectors.audience.internal") }, { value: "public", label: t("connectors.audience.public") }]} onChange={setAudience} />
        <p className="text-sm text-ink-muted">{t("connectors.realValues")}</p>
        {test.data && !test.data.ok ? <ErrorState title={t("connectors.test.failed")} description={test.data.error ?? ""} /> : null}
        {test.data?.ok ? (
          <div data-testid="connector-test" className="flex flex-col gap-1 rounded-md bg-surface-sunken p-3">
            <p className="text-md font-medium text-ink-primary">{tn("connectors.tools", test.data.tools?.length ?? 0)}</p>
            <ul className="flex flex-col gap-1">
              {(test.data.tools ?? []).map((tool) => (
                <li key={tool.id} className="text-sm text-ink-secondary">
                  <span className="text-ink-primary">{tool.name}</span> {tool.description}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {add.isError ? <ErrorState title={t("connectors.add.failed")} description={add.error instanceof ApiRequestError ? add.error.detail.message : ""} /> : null}
        <div className="flex flex-wrap gap-2">
          <Button loading={test.isPending} disabled={!url.trim()} onClick={() => test.mutate(input)}>{t("connectors.test")}</Button>
          <Button type="submit" variant="primary" loading={add.isPending} disabled={!name.trim() || !test.data?.ok}>{t("connectors.add.confirm")}</Button>
        </div>
      </form>
    </Dialog>
  );
}

function OtherConnectors() {
  const connectors = useConnectors();
  const servers = (connectors.data?.connectors ?? []).filter((row) => row.kind === "mcp");
  return (
    <Card title={t("connectors.mcp")} description={t("connectors.mcp.description")} aside={<AddServer />}>
      {connectors.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {connectors.isError ? <ErrorState title={t("connectors.error")} onRetry={() => void connectors.refetch()} /> : null}
      {connectors.isSuccess && !servers.length ? <EmptyState icon="connectors" title={t("connectors.mcp.empty")} /> : null}
      <div className="flex flex-col gap-2">
        {servers.map((connector) => (
          <ServerRow key={connector.id} connector={connector} />
        ))}
      </div>
    </Card>
  );
}

/** Used on its own page and in Settings, so the two can't drift apart. */
export function ConnectorsContent() {
  return (
    <div className="flex flex-col gap-4">
      <EmailConnector />
      <OtherConnectors />
    </div>
  );
}

export function ConnectorsScreen() {
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-5 p-6">
      <PageHeader title={t("nav.connectors")} summary={t("connectors.description")} />
      <ConnectorsContent />
    </div>
  );
}
