"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { ErrorBoundary } from "@/ui/primitives/ErrorBoundary";
import { Card } from "@/ui/primitives/Card";
import { ActiveMark } from "@/ui/primitives/Motion";
import { t, type StringKey } from "@/ui/strings";
import { ConnectorsContent } from "@/ui/features/connectors/ConnectorsScreen";
import { CategorySettings } from "./CategorySettings";
import { GuardSettings, NotificationSettings, PermissionsSettings, SendCheckSettingsCard, UsageSettings } from "./AgentSettings";
import { ContextCard, MailAgentCard } from "./AgentRunSettings";
import { AppearanceSettings } from "./AppearanceSettings";
import { LocalModelSettings } from "./LocalModelSettings";
import { ModelSettings } from "./ModelSettings";
import { PreferencesSettings } from "./PreferencesSettings";
import { ProfileForm } from "./ProfileForm";
import { RulesSettings } from "./RulesSettings";
import { AboutSettings, HomeSettings, NetworkSettings, ResetSettings } from "./SystemSettings";

const SECTIONS: readonly { id: string; group: StringKey; label: StringKey; content: () => ReactNode }[] = [
  { id: "appearance", group: "settings.group.you", label: "settings.appearance.title", content: () => <AppearanceSettings /> },
  {
    id: "profile", group: "settings.group.you",
    label: "settings.section.profile",
    content: () => (
      <Card title={t("settings.section.profile")} description={t("setup.profile.description")}>
        <ProfileForm action={t("settings.save")} />
      </Card>
    ),
  },
  { id: "preferences", group: "settings.group.you", label: "settings.section.preferences", content: () => <PreferencesSettings /> },
  { id: "connectors", group: "settings.group.mail", label: "nav.connectors", content: () => <ConnectorsContent /> },
  { id: "categories", group: "settings.group.mail", label: "nav.categories", content: () => <CategorySettings /> },
  { id: "rules", group: "settings.group.mail", label: "settings.section.rules", content: () => <RulesSettings /> },
  { id: "send-checks", group: "settings.group.mail", label: "checks.title", content: () => <SendCheckSettingsCard /> },
  { id: "models", group: "settings.group.agents", label: "settings.models.title", content: () => <ModelSettings /> },
  { id: "local-models", group: "settings.group.agents", label: "semantic.title", content: () => <LocalModelSettings /> },
  { id: "mail-agent", group: "settings.group.agents", label: "agentRuns.mail.title", content: () => <MailAgentCard /> },
  { id: "context", group: "settings.group.agents", label: "context.title", content: () => <ContextCard /> },
  { id: "permissions", group: "settings.group.agents", label: "permissions.title", content: () => <PermissionsSettings /> },
  { id: "guard", group: "settings.group.agents", label: "guard.title", content: () => <GuardSettings /> },
  { id: "usage", group: "settings.group.agents", label: "usage.title", content: () => <UsageSettings /> },
  { id: "notifications", group: "settings.group.agents", label: "notifications.title", content: () => <NotificationSettings /> },
  { id: "home", group: "settings.group.system", label: "settings.section.home", content: () => <HomeSettings /> },
  { id: "network", group: "settings.group.system", label: "settings.section.network", content: () => <NetworkSettings /> },
  { id: "reset", group: "settings.group.system", label: "reset.title", content: () => <ResetSettings /> },
  { id: "about", group: "settings.group.system", label: "settings.section.about", content: () => <AboutSettings /> },
];

export function SettingsLayout() {
  const requested = useSearchParams().get("section");
  const current = SECTIONS.find((section) => section.id === requested) ?? (SECTIONS[0] as (typeof SECTIONS)[number]);
  return (
    <div className="mx-auto flex max-w-page flex-col gap-5 p-6">
      <h1 className="font-serif text-display text-ink-primary">{t("settings.title")}</h1>
      <div className="flex items-start gap-6">
        <nav aria-label={t("settings.title")} className="sticky top-0 w-rail-wide shrink-0">
          <div className="flex flex-col gap-4">
            {[...new Set(SECTIONS.map((section) => section.group))].map((group) => (
              <div key={group}>
                <p className="mb-1 px-3 text-sm text-ink-muted">{t(group)}</p>
                <ul className="flex flex-col gap-px">
                  {SECTIONS.filter((section) => section.group === group).map((section) => (
                    <li key={section.id}>
                      <Link
                        href={`/settings?section=${section.id}`}
                        aria-current={section.id === current.id ? "page" : undefined}
                        className={`focus-ring relative block rounded-md px-3 py-1 text-md transition-colors duration-fast ${section.id === current.id ? "text-ink-primary" : "text-ink-secondary hover:bg-surface-raised hover:text-ink-primary"}`}
                      >
                        {section.id === current.id ? <ActiveMark group="settings-active" /> : null}
                        <span className="relative">{t(section.label)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </nav>
        <div className="min-w-0 flex-1">
          <ErrorBoundary key={current.id}>
            <div className="animate-rise">{current.content()}</div>
          </ErrorBoundary>
        </div>
      </div>
    </div>
  );
}
