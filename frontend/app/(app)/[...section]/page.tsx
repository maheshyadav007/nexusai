import { notFound } from "next/navigation";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { findNavItem } from "@/ui/shell/nav";
import { t } from "@/ui/strings";

// Screens in the sidebar that later stages replace. Unknown paths are real 404s.
export default async function ComingLaterPage({ params }: { params: Promise<{ section: string[] }> }) {
  const { section } = await params;
  const item = findNavItem(`/${section.join("/")}`);
  if (!item?.arrives) notFound();
  return (
    <div className="mx-auto max-w-content p-6">
      <h1 className="mb-4 font-serif text-display text-ink-primary">{t(item.label)}</h1>
      <EmptyState icon={item.icon} title={t("placeholder.title")} description={t(item.arrives)} />
    </div>
  );
}
