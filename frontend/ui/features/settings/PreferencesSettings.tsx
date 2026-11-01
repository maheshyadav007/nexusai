"use client";

import { useSettings, useUpdateSettings } from "@/ui/client/settings";
import { Card } from "@/ui/primitives/Card";
import { Select } from "@/ui/primitives/Select";
import { SettingRow } from "@/ui/primitives/SettingRow";
import { t } from "@/ui/strings";

const SCREENS = [
  { value: "today", label: t("nav.today") },
  { value: "inbox", label: t("nav.priority") },
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
      <SettingRow label={t("preferences.screen")}>
        <Select compact label={t("preferences.screen")} {...(settings.data?.default_screen ? { value: settings.data.default_screen } : {})} options={SCREENS} onChange={(default_screen) => update.mutate({ default_screen: default_screen as "today" | "inbox" })} />
      </SettingRow>
      <SettingRow label={t("preferences.date")}>
        <Select compact label={t("preferences.date")} {...(settings.data?.date_format ? { value: settings.data.date_format } : {})} options={DATES} onChange={(date_format) => update.mutate({ date_format: date_format as (typeof DATES)[number]["value"] })} />
      </SettingRow>
      <SettingRow label={t("preferences.time")}>
        <Select compact label={t("preferences.time")} {...(settings.data?.time_format ? { value: settings.data.time_format } : {})} options={TIMES} onChange={(time_format) => update.mutate({ time_format: time_format as (typeof TIMES)[number]["value"] })} />
      </SettingRow>
    </Card>
  );
}
