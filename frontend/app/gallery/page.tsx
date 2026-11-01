import { notFound } from "next/navigation";
import { GalleryContent } from "@/ui/gallery/GalleryContent";

// Development only: every component in every state, for unslop and visual tests.
export default function GalleryPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <GalleryContent />;
}
