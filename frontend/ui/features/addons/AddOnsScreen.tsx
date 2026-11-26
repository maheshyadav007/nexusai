"use client";

import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { useConnectors } from "@/ui/client/connectors";
import type { InstalledPlugin, InstallResult } from "@/ui/client/contracts.generated";
import { useLeadName } from "@/ui/client/home";
import { useExportPlugin, useInstall, usePlugins, useRemovePlugin, useSkills } from "@/ui/client/work";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { OtherConnectors } from "@/ui/features/connectors/ConnectorsScreen";
import { SkillsScreen } from "@/ui/features/agent/SkillsScreen";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Textarea } from "@/ui/primitives/Input";
import { PageHeader } from "@/ui/primitives/PageHeader";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Tabs } from "@/ui/primitives/Tabs";
import { t, tn } from "@/ui/strings";

// Plugins the person made themselves live in their Home, so their source path says so.
const YOURS = /[\\/]plugins[\\/][^\\/]+[\\/]?$/;

/** What one install did, in a sentence or a few. */
export function installSummary(done: InstallResult, lead: string): string[] {
  const lines = [t(done.kind === "plugin" ? "addons.done.plugin" : done.kind === "skill" ? "addons.done.skill" : "addons.done.servers", { name: done.name })];
  const on = done.on ?? [];
  const waiting = done.waiting ?? [];
  const needs = done.needs ?? [];
  const skipped = done.skipped ?? [];
  if (on.length && done.kind !== "skill") lines.push(t("addons.done.on", { names: on.join(", ") }));
  if (waiting.length) lines.push(t("addons.done.waiting", { names: waiting.join(", ") }));
  if (needs.length) lines.push(t("addons.done.needs", { names: needs.join(", "), lead }));
  if (skipped.length) lines.push(t("addons.done.skipped", { names: skipped.join(", ") }));
  return lines;
}

function InstallBox() {
  const [source, setSource] = useState("");
  const [done, setDone] = useState<InstallResult | null>(null);
  const install = useInstall();
  const assistant = useAssistant();
  const lead = useLeadName();
  const failed = install.error instanceof ApiRequestError ? install.error.message : install.isError ? t("addons.plugins.error") : null;
  return (
    <form
      aria-label={t("addons.install.action")}
      className="flex flex-col gap-3 rounded-lg border border-line-subtle bg-surface-raised p-4"
      onSubmit={(event) => {
        event.preventDefault();
        setDone(null);
        install.mutate({ source: source.trim() }, { onSuccess: (result) => { setDone(result); setSource(""); } });
      }}
    >
      <Field label={t("addons.install.label")}>
        {({ invalid, ...control }) => <Textarea invalid={invalid} rows={2} spellCheck={false} value={source} onChange={(event) => setSource(event.target.value)} {...control} />}
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" loading={install.isPending} disabled={!source.trim()}>{t("addons.install.action")}</Button>
        <Button type="button" variant="quiet" onClick={() => assistant.start({ text: t("addons.install.makePrompt"), title: t("addons.install.makePrompt") })}>{t("addons.install.make", { name: lead })}</Button>
      </div>
      {done ? <div data-testid="install-result" role="status" className="flex flex-col gap-1 text-md text-ink-secondary">{installSummary(done, lead).map((line) => <p key={line}>{line}</p>)}</div> : null}
      {failed ? <p role="alert" className="text-md text-status-danger">{failed}</p> : null}
    </form>
  );
}

function PluginRow({ plugin }: { plugin: InstalledPlugin }) {
  const remove = useRemovePlugin();
  const exported = useExportPlugin();
  const yours = YOURS.test(plugin.source) && !plugin.source.includes("://");
  const skipped = plugin.skipped ?? [];
  return (
    <li data-testid="plugin" className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 rounded-lg border border-line-subtle bg-surface-raised p-4">
      <div className="flex min-w-0 flex-col gap-2">
        <span className="flex flex-wrap items-center gap-2 text-lg font-medium text-ink-primary">
          {plugin.display_name || plugin.name}
          {yours ? <Badge tone="accent">{t("addons.yours")}</Badge> : null}
          {skipped.length ? <Badge tone="warning">{tn("addons.skipped", skipped.length)}</Badge> : null}
        </span>
        {plugin.description ? <span className="text-md text-ink-secondary">{plugin.description}</span> : null}
        <span className="flex flex-wrap gap-1">
          {(plugin.skills ?? []).map((name) => <Badge key={`s-${name}`}>{t("addons.skill", { name })}</Badge>)}
          {(plugin.servers ?? []).map((server) => <Badge key={`m-${server.name}`}>{t("addons.server", { name: server.name })}</Badge>)}
        </span>
        <span className="break-all text-sm text-ink-muted">{plugin.source}</span>
        {exported.data ? <span role="status" className="break-all text-sm text-ink-secondary">{t("addons.exported", { path: exported.data.path })}</span> : null}
      </div>
      <div className="flex items-center gap-1">
        {yours ? <Button variant="quiet" loading={exported.isPending} onClick={() => exported.mutate({ name: plugin.name })}>{t("addons.export")}</Button> : null}
        <Button variant="quiet" loading={remove.isPending} onClick={() => remove.mutate({ name: plugin.name })}>{t("addons.remove")}</Button>
      </div>
    </li>
  );
}

function PluginList() {
  const listed = usePlugins();
  if (listed.isPending) return <Skeleton className="h-6 w-full" />;
  if (listed.isError) return <ErrorState title={t("addons.plugins.error")} onRetry={() => void listed.refetch()} />;
  const plugins = listed.data.plugins;
  if (!plugins.length) return <EmptyState icon="connectors" title={t("addons.plugins.empty")} />;
  return <ul className="flex flex-col gap-2">{plugins.map((plugin) => <PluginRow key={plugin.name} plugin={plugin} />)}</ul>;
}

export function AddOnsScreen() {
  const plugins = usePlugins();
  const connectors = useConnectors();
  const skills = useSkills();
  const servers = (connectors.data?.connectors ?? []).filter((row) => row.kind === "mcp").length;
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-5 p-6">
      <PageHeader title={t("nav.addons")} summary={t("addons.summary")} />
      <InstallBox />
      <Tabs
        label={t("addons.tabs")}
        tabs={[
          { value: "plugins", label: t("addons.tab.plugins", { count: plugins.data?.plugins.length ?? 0 }), content: <div className="pt-4"><PluginList /></div> },
          { value: "servers", label: t("addons.tab.servers", { count: servers }), content: <div className="pt-4"><OtherConnectors /></div> },
          { value: "skills", label: t("addons.tab.skills", { count: skills.data?.skills.length ?? 0 }), content: <div className="pt-4"><SkillsScreen /></div> },
        ]}
      />
    </div>
  );
}
