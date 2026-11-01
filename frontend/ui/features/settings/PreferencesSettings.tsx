"use client";

import { useSettings, useUpdateSettings } from "@/ui/client/settings";
import { Card } from "@/ui/primitives/Card";
import { Segmented } from "@/ui/primitives/Segmented";
import { t } from "@/ui/strings";

const SCREENS = [
  { value: "today", label: t("nav.today") },
  { value: "inbox", label: t("nav.inbox") },
] as const;
const DATES = [
  { value: "system", label: t("preferences.system") },
  { value: "day-month", label: t("preferences.date.dayMonth") },
  { value: "month-day", label: t("preferences.date.monthDay") },
  { value: "iso", label: t("preferences.date.iso") },
] as const;
const TIMES = [
  { value: "system", label: t("preferences.system") },
  { value: "12", label: t("preferences.time.12") },
  { value: "24", label: t("preferences.time.24") },
] as const;

export function PreferencesSettings() {
  const settings = useSettings();
  const update = useUpdateSettings();
  return (
    <Card title={t("settings.section.preferences")}>
      <div className="flex flex-col gap-4">
        <Segmented label={t("preferences.screen")} value={settings.data?.default_screen} options={SCREENS} onChange={(default_screen) => update.mutate({ default_screen })} />
        <Segmented label={t("preferences.date")} value={settings.data?.date_format} options={DATES} onChange={(date_format) => update.mutate({ date_format })} />
        <Segmented label={t("preferences.time")} value={settings.data?.time_format} options={TIMES} onChange={(time_format) => update.mutate({ time_format })} />
      </div>
    </Card>
  );
}
