import { notFound } from "next/navigation";
import { Card } from "@/ui/primitives/Card";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { t } from "@/ui/strings";

// Development only: every component in every state, for unslop and visual tests.
export default function GalleryPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <main className="mx-auto flex max-w-content flex-col gap-5 p-6">
      <h1 className="font-serif text-display">{t("gallery.title")}</h1>
      <Card title={t("gallery.title")} description={t("gallery.sample")}>
        <div className="flex gap-3">
          <StatusDot tone="running" />
          <StatusDot tone="waiting" />
          <StatusDot tone="done" />
          <StatusDot tone="failed" />
        </div>
      </Card>
    </main>
  );
}
