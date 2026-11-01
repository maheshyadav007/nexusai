"use client";

import { useSettings, useUpdateSettings } from "@/ui/client/settings";
import { Card } from "@/ui/primitives/Card";
import { Segmented } from "@/ui/primitives/Segmented";
import { t } from "@/ui/strings";
import { THEMES } from "@/ui/theme/generated/theme-list";

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

export function AppearanceSettings() {
  const settings = useSettings();
  const update = useUpdateSettings();
  return (
    <Card title={t("settings.appearance.title")} description={t("settings.appearance.description")}>
      <div className="flex flex-col gap-4" aria-busy={settings.isPending}>
        <Segmented
          label={t("settings.theme")}
          value={settings.data?.theme}
          options={THEMES.map((theme) => ({ value: theme.id as string, label: theme.name }))}
          onChange={(theme) => update.mutate({ theme })}
        />
        <Segmented
          label={t("settings.density")}
          value={settings.data?.density}
          options={DENSITIES}
          onChange={(density) => update.mutate({ density })}
        />
        <Segmented
          label={t("settings.textSize")}
          value={settings.data?.text_size}
          options={TEXT_SIZES}
          onChange={(text_size) => update.mutate({ text_size })}
        />
        {update.isError || settings.isError ? (
          <p role="alert" className="text-sm text-status-danger">
            {t("settings.error")}
          </p>
        ) : null}
      </div>
    </Card>
  );
}
