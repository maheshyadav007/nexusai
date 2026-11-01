"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { ErrorBoundary } from "@/ui/primitives/ErrorBoundary";
import { Card } from "@/ui/primitives/Card";
import { t, type StringKey } from "@/ui/strings";
import { PstImportCard } from "@/ui/features/mail/PstImportCard";
import { AccountSettings } from "./AccountSettings";
import { AppearanceSettings } from "./AppearanceSettings";
import { ModelSettings } from "./ModelSettings";
import { PreferencesSettings } from "./PreferencesSettings";
import { ProfileForm } from "./ProfileForm";
import { RulesSettings } from "./RulesSettings";
import { AboutSettings, HomeSettings, NetworkSettings } from "./SystemSettings";

// Accounts, permissions, connectors, rules and more join as their stages arrive.
const SECTIONS: readonly { id: string; label: StringKey; content: () => ReactNode }[] = [
  { id: "appearance", label: "settings.appearance.title", content: () => <AppearanceSettings /> },
  {
    id: "profile",
    label: "settings.section.profile",
    content: () => (
      <Card title={t("settings.section.profile")} description={t("setup.profile.description")}>
        <ProfileForm action={t("settings.save")} />
      </Card>
    ),
  },
  { id: "preferences", label: "settings.section.preferences", content: () => <PreferencesSettings /> },
  { id: "accounts", label: "settings.section.accounts", content: () => <AccountSettings /> },
  { id: "archive", label: "nav.archive", content: () => <PstImportCard /> },
  { id: "rules", label: "settings.section.rules", content: () => <RulesSettings /> },
  { id: "models", label: "settings.models.title", content: () => <ModelSettings /> },
  { id: "home", label: "settings.section.home", content: () => <HomeSettings /> },
  { id: "network", label: "settings.section.network", content: () => <NetworkSettings /> },
  { id: "about", label: "settings.section.about", content: () => <AboutSettings /> },
];

export function SettingsLayout() {
  const requested = useSearchParams().get("section");
  const current = SECTIONS.find((section) => section.id === requested) ?? (SECTIONS[0] as (typeof SECTIONS)[number]);
  return (
    <div className="mx-auto flex max-w-page flex-col gap-5 p-6">
      <h1 className="font-serif text-display text-ink-primary">{t("settings.title")}</h1>
      <div className="flex items-start gap-6">
        <nav aria-label={t("settings.title")} className="sticky top-0 w-rail-wide shrink-0">
          <ul className="flex flex-col gap-px">
            {SECTIONS.map((section) => (
              <li key={section.id}>
                <Link
                  href={`/settings?section=${section.id}`}
                  aria-current={section.id === current.id ? "page" : undefined}
                  className={`focus-ring block rounded-md px-3 py-1 text-md transition-colors duration-fast ${section.id === current.id ? "bg-surface-sunken font-medium text-ink-primary" : "text-ink-secondary hover:bg-surface-sunken hover:text-ink-primary"}`}
                >
                  {t(section.label)}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 flex-1">
          <ErrorBoundary key={current.id}>{current.content()}</ErrorBoundary>
        </div>
      </div>
    </div>
  );
}
