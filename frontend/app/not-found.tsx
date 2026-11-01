import { EmptyState } from "@/ui/primitives/EmptyState";
import { TextLink } from "@/ui/primitives/TextLink";
import { t } from "@/ui/strings";

export default function NotFound() {
  return (
    <main className="mx-auto max-w-content p-6">
      <h1 className="mb-4 font-serif text-display text-ink-primary">{t("notFound.title")}</h1>
      <EmptyState icon="search" title={t("notFound.description")} action={<TextLink href="/">{t("notFound.home")}</TextLink>} />
    </main>
  );
}
