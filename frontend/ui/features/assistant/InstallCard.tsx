"use client";

import { usePlugins, useRemovePlugin, useSkills } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { TextLink } from "@/ui/primitives/TextLink";
import { t, tn } from "@/ui/strings";
import { Shell } from "./Cards";
import { installedName, type ToolPart } from "./parts";

function Row({ label, state, tone }: { label: string; state: string; tone: "on" | "waiting" | "muted" }) {
  const color = tone === "on" ? "text-status-success" : tone === "waiting" ? "text-status-warning" : "text-ink-muted";
  return (
    <li className="flex items-center justify-between gap-3 border-t border-line-subtle py-2 text-md">
      <span className="min-w-0 break-words text-ink-primary">{label}</span>
      <span className={`shrink-0 text-sm ${color}`}>{state}</span>
    </li>
  );
}

/** A plugin installed from chat: what's on now, what waits for a look, and what isn't used here. Live, so a skill switched on later shows as on. */
export function InstallCard({ part }: { part: ToolPart }) {
  const name = installedName(part);
  const plugins = usePlugins();
  const skills = useSkills();
  const remove = useRemovePlugin();
  const plugin = (plugins.data?.plugins ?? []).find((item) => item.name === name);
  const active = new Set((skills.data?.skills ?? []).filter((skill) => skill.active).map((skill) => skill.name));
  const waiting = new Map((skills.data?.proposals ?? []).filter((item) => item.status === "waiting").map((item) => [item.name, item.flags.length]));
  if (!name) return null;
  return (
    <Shell testid="install-card">
      <div className="flex flex-col gap-1">
        <span className="text-sm text-ink-muted">{t(plugin ? "chat.install.label" : "chat.install.removed")}</span>
        <span className="text-lg font-medium text-ink-primary">{plugin?.display_name || name}</span>
      </div>
      {plugin ? (
        <ul className="flex flex-col">
          {(plugin.skills ?? []).map((skill) => {
            const flags = waiting.get(skill);
            if (active.has(skill)) return <Row key={skill} label={t("addons.skill", { name: skill })} state={t("chat.install.on")} tone="on" />;
            if (flags !== undefined) return <Row key={skill} label={t("addons.skill", { name: skill })} state={tn("chat.install.check", flags)} tone="waiting" />;
            return <Row key={skill} label={t("addons.skill", { name: skill })} state={t("chat.install.off")} tone="muted" />;
          })}
          {(plugin.servers ?? []).map((server) => (
            <Row key={`m-${server.name}`} label={t("addons.server", { name: server.name })} state={t((plugin.connector_ids ?? []).length ? "chat.install.added" : "chat.install.needs")} tone={(plugin.connector_ids ?? []).length ? "on" : "waiting"} />
          ))}
          {(plugin.skipped ?? []).map((what) => <Row key={`x-${what}`} label={what} state={t("chat.install.notUsed")} tone="muted" />)}
        </ul>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <TextLink href="/addons">{t("chat.install.open")}</TextLink>
        {plugin ? <Button variant="quiet" loading={remove.isPending} onClick={() => remove.mutate({ name: plugin.name })}>{t("addons.remove")}</Button> : null}
      </div>
    </Shell>
  );
}
