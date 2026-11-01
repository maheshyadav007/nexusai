import { EmptyState } from "@/ui/primitives/EmptyState";
import { t } from "@/ui/strings";

export default function TodayPage() {
  return (
    <div className="mx-auto max-w-content p-6">
      <h1 className="mb-4 font-serif text-display text-ink-primary">{t("nav.today")}</h1>
      <EmptyState icon="today" title={t("today.empty.title")} description={t("today.empty.description")} />
    </div>
  );
}
