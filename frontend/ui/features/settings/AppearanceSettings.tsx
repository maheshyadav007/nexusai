"use client";

import { useSettings, useUpdateSettings } from "@/ui/client/settings";
import { Card } from "@/ui/primitives/Card";
import { Segmented } from "@/ui/primitives/Segmented";
import { SettingRow } from "@/ui/primitives/SettingRow";
import { TileGroup } from "@/ui/primitives/TileGroup";
import { t } from "@/ui/strings";
import { THEMES } from "@/ui/theme/generated/theme-list";

const ACCENTS = [
  { value: "terracotta", label: t("settings.accent.terracotta") },
  { value: "cobalt", label: t("settings.accent.cobalt") },
  { value: "moss", label: t("settings.accent.moss") },
  { value: "plum", label: t("settings.accent.plum") },
] as const;

const DENSITIES = [
  { value: "compact", label: t("settings.density.compact") },
  { value: "comfortable", label: t("settings.density.comfortable") },
  { value: "spacious", label: t("settings.density.spacious") },
] as const;

const TEXT_SIZES = [
  { value: "small", label: t("settings.textSize.small") },
  { value: "medium", label: t("settings.textSize.medium") },
  { value: "large", label: t("settings.textSize.large") },
] as const;

function ThemePreview({ theme, accent }: { theme: string; accent: string }) {
  // Scoped to its own theme, so it shows that theme's real colors in the chosen accent.
  return (
    <span data-theme={theme} data-accent={accent} className="flex h-7 w-rail flex-col justify-end gap-1 overflow-hidden rounded-sm border border-line-subtle bg-surface-page p-1">
      <span className="h-1 w-3/4 rounded-full bg-ink-primary" />
      <span className="h-1 w-1/2 rounded-full bg-ink-muted" />
      <span className="h-1 w-1/4 rounded-full bg-accent-default" />
    </span>
  );
}

function SystemPreview({ accent }: { accent: string }) {
  return (
    <span className="flex h-7 w-rail overflow-hidden rounded-sm border border-line-subtle">
      {THEMES.slice(0, 2).map((theme) => (
        <span key={theme.id} data-theme={theme.id} data-accent={accent} className="flex flex-1 flex-col justify-end gap-1 bg-surface-page p-1">
          <span className="h-1 w-full rounded-full bg-ink-primary" />
          <span className="h-1 w-1/2 rounded-full bg-accent-default" />
        </span>
      ))}
    </span>
  );
}

function AccentPreview({ accent, theme }: { accent: string; theme: string }) {
  return <span data-theme={theme} data-accent={accent} className="block h-5 w-5 rounded-full bg-accent-default" />;
}

export function AppearanceSettings({ brief = false }: { brief?: boolean }) {
  const settings = useSettings();
  const update = useUpdateSettings();
  const accent = settings.data?.accent ?? ACCENTS[0].value;
  const current = settings.data?.theme && settings.data.theme !== "system" ? settings.data.theme : THEMES[0]?.id ?? "";
  return (
    <div className="flex flex-col gap-5" aria-busy={settings.isPending}>
      <Card title={t("settings.theme")} description={t("settings.appearance.description")}>
        <TileGroup
          label={t("settings.theme")}
          value={settings.data?.theme}
          onChange={(theme) => update.mutate({ theme })}
          tiles={[
            ...THEMES.map((theme) => ({ value: theme.id as string, label: theme.name, preview: <ThemePreview theme={theme.id} accent={accent} /> })),
            { value: "system", label: t("settings.theme.system"), preview: <SystemPreview accent={accent} /> },
          ]}
        />
      </Card>
      <Card title={t("settings.accent")}>
        <TileGroup label={t("settings.accent")} value={settings.data?.accent} onChange={(accent) => update.mutate({ accent })} tiles={ACCENTS.map((accent) => ({ value: accent.value, label: accent.label, preview: <AccentPreview accent={accent.value} theme={current} /> }))} />
      </Card>
      {brief ? null : (
      <Card title={t("settings.appearance.layout")}>
        <SettingRow label={t("settings.density")} wide>
          <Segmented hideLabel label={t("settings.density")} value={settings.data?.density} options={DENSITIES} onChange={(density) => update.mutate({ density })} />
        </SettingRow>
        <SettingRow label={t("settings.textSize")} wide>
          <Segmented hideLabel label={t("settings.textSize")} value={settings.data?.text_size} options={TEXT_SIZES} onChange={(text_size) => update.mutate({ text_size })} />
        </SettingRow>
      </Card>
      )}
      {update.isError || settings.isError ? (
        <p role="alert" className="text-sm text-status-danger">
          {t("settings.error")}
        </p>
      ) : null}
    </div>
  );
}
