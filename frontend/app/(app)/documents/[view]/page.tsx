import { notFound } from "next/navigation";
import { DocumentsScreen, type DocumentView } from "@/ui/features/documents/DocumentsScreen";

const VIEWS: readonly string[] = ["all", "uploaded", "from-email", "home"];

export default async function Page({ params }: { params: Promise<{ view: string }> }) {
  const { view } = await params;
  if (!VIEWS.includes(view)) notFound();
  return <DocumentsScreen key={view} view={view as DocumentView} />;
}
