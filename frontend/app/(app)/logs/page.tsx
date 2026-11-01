import { EventInspector } from "@/ui/features/inspector/EventInspector";
import { LogViewer } from "@/ui/features/logs/LogViewer";
import { Tabs } from "@/ui/primitives/Tabs";
import { t } from "@/ui/strings";

export default function LogsPage() {
  return (
    <div className="mx-auto flex max-w-page flex-col gap-5 p-6">
      <h1 className="font-serif text-display text-ink-primary">{t("nav.logs")}</h1>
      <Tabs
        label={t("nav.logs")}
        tabs={[
          { value: "logs", label: t("logs.tab.logs"), content: <LogViewer /> },
          { value: "events", label: t("logs.tab.events"), content: <EventInspector /> },
        ]}
      />
    </div>
  );
}
