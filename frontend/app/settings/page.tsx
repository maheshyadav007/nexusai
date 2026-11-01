import { AppearanceSettings } from "@/ui/features/settings/AppearanceSettings";
import { EventInspector } from "@/ui/features/inspector/EventInspector";
import { ErrorBoundary } from "@/ui/primitives/ErrorBoundary";
import { t } from "@/ui/strings";

export default function SettingsPage() {
  return (
    <main className="mx-auto flex max-w-content flex-col gap-5 p-6">
      <h1 className="font-serif text-display text-ink-primary">{t("settings.title")}</h1>
      <ErrorBoundary>
        <AppearanceSettings />
      </ErrorBoundary>
      <ErrorBoundary>
        <EventInspector />
      </ErrorBoundary>
    </main>
  );
}
