import { notFound } from "next/navigation";
import demo from "@/ui/gallery/fixtures/demo.json";
import { AppShell } from "@/ui/shell/AppShell";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { t } from "@/ui/strings";

// Development only: the shell with demo data, showing states real data can't reach yet.
export default function GalleryShellPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <AppShell activities={demo.activities} counts={demo.counts}>
      <div className="mx-auto max-w-content p-6">
        <h1 className="mb-4 font-serif text-display text-ink-primary">{t("nav.today")}</h1>
        <EmptyState icon="today" title={t("today.empty.title")} description={t("today.empty.description")} />
      </div>
    </AppShell>
  );
}
